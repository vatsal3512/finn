"""One client for every model call: routing, caching, key failover and usage logging.

Routing by difficulty (decision D9, and the brief's efficiency bonus)
- LITE   gemini-3.5-flash-lite, minimal thinking: sorting filings, one-line summaries,
         pulling a bio out of a filing. High volume, simple judgement.
- FLASH  gemini-3.8-flash, low thinking: reading results tables, including from page
         images, and pulling guidance statements out of transcripts.
- REASON gemini-3.8-flash, high thinking: the few calls that compare and judge, such as
         promised vs delivered.

Every call returns a validated pydantic object. Answers are cached by task, prompt
version and input, so re-running the pipeline costs nothing for work already done.

Failover order: each Gemini key in turn, then Groq for text-only tasks, then, for Flash
tasks, a step down to Flash-Lite. Image tasks have no Groq fallback.

Two kinds of failure are told apart, because they need opposite responses:
- A quota limit belongs to one key. The next key will answer.
- A capacity error (503 "high demand", 504, or no answer within 90 seconds) belongs to the
  model. On 27 Oct 2026, 21 of 23 gemini-3.8-flash calls failed this way across five keys,
  and one took 270 seconds. After two keys report it, the model is skipped for three
  minutes, instead of every key queueing for an answer none of them can get.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar

import httpx
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from finn.ai.keys import Key, KeyPool, keys_from_env, seconds_until_quota_reset
from finn.config import ROOT
from finn.store import now_iso

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class Tier(StrEnum):
    LITE = "lite"
    FLASH = "flash"
    REASON = "reason"


@dataclass(frozen=True)
class Route:
    model: str
    thinking: str


GEMINI_ROUTES = {
    Tier.LITE: Route("gemini-3.5-flash-lite", "minimal"),
    Tier.FLASH: Route("gemini-3.8-flash", "low"),
    Tier.REASON: Route("gemini-3.8-flash", "high"),
}
GROQ_MODEL = "openai/gpt-oss-120b"  # production model with JSON-schema output

GEMINI_MIN_INTERVAL = 6.5  # seconds per key and model: about 9 a minute, under the ~10 cap
GROQ_MIN_INTERVAL = 2.2  # about 27 a minute, under the 30 cap

REQUEST_TIMEOUT_S = 90  # a slow answer is a capacity problem; waiting longer does not help
BUSY_AFTER = 2  # keys reporting a capacity error before the model is treated as busy
BUSY_SECONDS = 180


class RateLimited(Exception):
    def __init__(self, message: str, daily: bool):
        super().__init__(message)
        self.daily = daily


class Transient(Exception):
    """Server error: worth one retry on the same key."""


class ModelBusy(Transient):
    """The model is overloaded for everyone. Another key on the same model will not help."""


class AIUnavailable(Exception):
    """Every key on every provider is resting or failing."""


@dataclass
class Reply:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None


class Backend(Protocol):
    provider: str

    def call(
        self,
        key: Key,
        model: str,
        thinking: str | None,
        system: str,
        prompt: str,
        images: Sequence[bytes],
        schema: type[BaseModel],
        max_output_tokens: int,
    ) -> Reply: ...


class GeminiBackend:
    provider = "gemini"

    def __init__(self) -> None:
        self._clients: dict[str, object] = {}

    def call(
        self, key, model, thinking, system, prompt, images, schema, max_output_tokens
    ) -> Reply:
        from google import genai
        from google.genai import errors, types

        client = self._clients.get(key.alias)
        if client is None:
            client = self._clients[key.alias] = genai.Client(
                api_key=key.secret,
                http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_S * 1000),
            )
        parts = [types.Part.from_bytes(data=img, mime_type="image/png") for img in images]
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_level=thinking) if thinking else None,
        )
        try:
            resp = client.models.generate_content(
                model=model, contents=[*parts, prompt], config=config
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                text = str(exc).lower()
                raise RateLimited(str(exc), daily="per day" in text or "perday" in text) from exc
            raise
        except errors.ServerError as exc:
            raise (ModelBusy if exc.code in (503, 504) else Transient)(str(exc)) from exc
        except httpx.TimeoutException as exc:
            raise ModelBusy(f"no answer in {REQUEST_TIMEOUT_S}s") from exc
        u = resp.usage_metadata
        return Reply(
            resp.text or "",
            getattr(u, "prompt_token_count", None),
            getattr(u, "candidates_token_count", None),
            getattr(u, "thoughts_token_count", None),
        )


class GroqBackend:
    provider = "groq"

    def __init__(self) -> None:
        self._clients: dict[str, object] = {}

    def call(
        self, key, model, thinking, system, prompt, images, schema, max_output_tokens
    ) -> Reply:
        import groq

        if images:
            raise ValueError("Groq fallback is text-only")
        client = self._clients.get(key.alias)
        if client is None:
            client = self._clients[key.alias] = groq.Groq(
                api_key=key.secret, max_retries=0, timeout=REQUEST_TIMEOUT_S
            )
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()},
                },
                max_completion_tokens=max_output_tokens,
            )
        except groq.RateLimitError as exc:
            raise RateLimited(str(exc), daily="per day" in str(exc).lower()) from exc
        except groq.APITimeoutError as exc:  # before APIConnectionError, its parent
            raise ModelBusy(str(exc)) from exc
        except groq.InternalServerError as exc:
            raise (ModelBusy if exc.status_code in (503, 504) else Transient)(str(exc)) from exc
        except groq.APIConnectionError as exc:
            raise Transient(str(exc)) from exc
        u = resp.usage
        return Reply(resp.choices[0].message.content or "", u.prompt_tokens, u.completion_tokens)


def cache_key(
    task: str, version: str, system: str, prompt: str, images: Sequence[bytes], tier: str = ""
) -> str:
    """The tier is part of the key: a deliberate step up in model quality must not be
    answered from the cheaper model's cache. Which provider answered is not, so a
    fallback answer is reused."""
    h = hashlib.sha256()
    for part in (task, version, system, prompt, tier):
        h.update(part.encode())
        h.update(b"\x00")
    for img in images:
        h.update(hashlib.sha256(img).digest())
    return h.hexdigest()


class LLM:
    def __init__(
        self,
        conn: sqlite3.Connection,
        gemini_keys: list[Key],
        groq_keys: list[Key],
        gemini: Backend | None = None,
        groq: Backend | None = None,
    ):
        self.conn = conn
        self.gemini_pool = KeyPool(conn, gemini_keys, GEMINI_MIN_INTERVAL)
        self.groq_pool = KeyPool(conn, groq_keys, GROQ_MIN_INTERVAL)
        self.gemini = gemini or GeminiBackend()
        self.groq = groq or GroqBackend()
        self.stats = {"cache_hits": 0, "calls": 0, "fallbacks": 0, "step_downs": 0, "failures": 0}
        self.last_model: str | None = None  # which model gave the latest answer
        self._busy_until: dict[str, float] = {}  # model -> monotonic time

    @classmethod
    def from_env(cls, conn: sqlite3.Connection) -> LLM:
        load_dotenv(ROOT / "backend" / ".env")
        return cls(
            conn, keys_from_env("gemini", "GEMINI_API_KEYS"), keys_from_env("groq", "GROQ_API_KEYS")
        )

    @property
    def configured(self) -> bool:
        return bool(self.gemini_pool) or bool(self.groq_pool)

    # ---------------------------------------------------------------- public

    def json(
        self,
        task: str,
        tier: Tier,
        prompt: str,
        schema: type[T],
        *,
        system: str,
        version: str,
        images: Sequence[bytes] = (),
        max_output_tokens: int = 4096,
    ) -> T:
        key = cache_key(task, version, system, prompt, images, tier.value)
        row = self.conn.execute(
            "SELECT response, model FROM ai_cache WHERE key = ?", (key,)
        ).fetchone()
        if row:
            self.stats["cache_hits"] += 1
            self.last_model = row[1]
            return schema.model_validate_json(row[0])

        # (backend, pool, model, thinking, kind). A "fallback" is a peer model on another
        # provider; a "step_down" is a cheaper model standing in for a busy one.
        route, lite = GEMINI_ROUTES[tier], GEMINI_ROUTES[Tier.LITE]
        attempts = [(self.gemini, self.gemini_pool, route.model, route.thinking, "primary")]
        if not images:
            attempts.append((self.groq, self.groq_pool, GROQ_MODEL, None, "fallback"))
        if tier is not Tier.LITE:
            attempts.append((self.gemini, self.gemini_pool, lite.model, lite.thinking, "step_down"))

        errors: list[str] = []
        for backend, pool, model, thinking, kind in attempts:
            if self._busy_until.get(model, 0.0) > time.monotonic():
                errors.append(f"{model}: busy")
                continue
            busy_reports = 0
            for k in pool.available(model):
                try:
                    result = self._try_key(backend, pool, k, model, thinking, task, system, prompt,
                                           images, schema, max_output_tokens, errors)  # fmt: skip
                except ModelBusy:
                    busy_reports += 1
                    if busy_reports >= BUSY_AFTER:
                        self._busy_until[model] = time.monotonic() + BUSY_SECONDS
                        log.warning("%s is over capacity; skipping it for %ss", model, BUSY_SECONDS)
                        break
                    continue
                if result is None:
                    continue
                if kind != "primary":
                    self.stats["fallbacks" if kind == "fallback" else "step_downs"] += 1
                # A step-down answer is used but not remembered, so the next run asks the
                # right model again.
                if kind != "step_down":
                    self.conn.execute(
                        "INSERT OR REPLACE INTO ai_cache (key, task, model, degraded, response, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            key,
                            task,
                            model,
                            int(kind != "primary"),
                            result.model_dump_json(),
                            now_iso(),
                        ),
                    )
                    self.conn.commit()
                self.last_model = model
                return result
        self.stats["failures"] += 1
        raise AIUnavailable(f"{task}: no key could answer. " + " | ".join(errors[-4:]))

    # ---------------------------------------------------------------- internals

    def _try_key(self, backend, pool, k, model, thinking, task, system, prompt, images,
                 schema, max_output_tokens, errors):  # fmt: skip
        for attempt in (1, 2):
            pool.pace(k, model)
            t0 = time.perf_counter()
            try:
                reply = backend.call(
                    k, model, thinking, system, prompt, images, schema, max_output_tokens
                )
                parsed = schema.model_validate_json(_strip_fences(reply.text))
            except RateLimited as exc:
                rest = seconds_until_quota_reset() if exc.daily else 65
                pool.rest(k, model, rest, "daily quota" if exc.daily else "per-minute limit")
                self._log(
                    backend,
                    model,
                    k,
                    task,
                    False,
                    t0,
                    error="rate limited (daily)" if exc.daily else "rate limited",
                )
                errors.append(f"{k.alias}: rate limited")
                return None
            except ModelBusy:
                self._log(backend, model, k, task, False, t0, error="model busy")
                errors.append(f"{k.alias}: {model} busy")
                raise
            except (Transient, ValidationError, json.JSONDecodeError) as exc:
                self._log(backend, model, k, task, False, t0, error=type(exc).__name__)
                errors.append(f"{k.alias}: {type(exc).__name__}")
                if attempt == 2:
                    return None
                continue
            except Exception as exc:  # noqa: BLE001 - e.g. invalid key; try the next one
                self._log(
                    backend,
                    model,
                    k,
                    task,
                    False,
                    t0,
                    error=f"{type(exc).__name__}: {str(exc)[:120]}",
                )
                errors.append(f"{k.alias}: {type(exc).__name__}")
                if "api key" in str(exc).lower() or "permission" in str(exc).lower():
                    pool.rest(k, model, 3600, "key rejected")
                return None
            self._log(backend, model, k, task, True, t0, reply=reply)
            self.stats["calls"] += 1
            return parsed
        return None

    def _log(
        self, backend, model, k, task, ok, t0, reply: Reply | None = None, error: str | None = None
    ):
        self.conn.execute(
            "INSERT INTO ai_usage (at, provider, model, key_alias, task, ok, input_tokens, output_tokens, "
            "thinking_tokens, latency_ms, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                now_iso(), backend.provider, model, k.alias, task, int(ok),
                reply.input_tokens if reply else None, reply.output_tokens if reply else None,
                reply.thinking_tokens if reply else None, int((time.perf_counter() - t0) * 1000), error,
            ),
        )  # fmt: skip
        self.conn.commit()


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else t
        t = t.rsplit("```", 1)[0]
    return t.strip()


def env_summary() -> dict[str, int]:
    """How many keys are configured, without revealing them."""
    load_dotenv(ROOT / "backend" / ".env")
    return {
        "gemini_keys": len(keys_from_env("gemini", "GEMINI_API_KEYS")),
        "groq_keys": len(keys_from_env("groq", "GROQ_API_KEYS")),
        "env_file": int(os.path.exists(ROOT / "backend" / ".env")),
    }
