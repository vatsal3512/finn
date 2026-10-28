"""The live API, for the two things that cannot be computed ahead of time: research on a
ticker nobody picked, and a question about a filing.

Everything else the app shows is static JSON written by the scheduled pipeline (decision
D8), so it opens instantly. This server exists for the moment someone types a ticker FINN
has never seen.

    uv run uvicorn finn.api:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from finn import blobstore
from finn.ai.llm import LLM, AIUnavailable, env_summary
from finn.config import DATA_DIR, EXPORT_DIR
from finn.contracts import AskAnswer
from finn.research import engine
from finn.research.ask import MAX_QUESTION, ask
from finn.store import connect

log = logging.getLogger(__name__)

SYMBOL = re.compile(r"^[A-Z0-9&-]{1,20}$")
PRECOMPUTED = EXPORT_DIR / "research"  # shipped with the app
LIVE = DATA_DIR / "research"  # written by live runs
FRESH = timedelta(days=7)
REFRESH_AFTER = timedelta(hours=1)  # a refresh request inside this window is served the cache
LIVE_BUDGET_S = 240  # model time for one live request, inside Vercel's 300-second limit

app = FastAPI(title="FINN", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
)


def _symbol(raw: str) -> str:
    s = raw.strip().upper().removesuffix(".NS")
    if not SYMBOL.match(s):
        raise HTTPException(422, "An NSE symbol is letters, digits, & or -, such as INFY or M&M.")
    return s


def _fresh(report: dict | None, max_age: timedelta) -> dict | None:
    if not report:
        return None
    age = datetime.now(UTC) - datetime.fromisoformat(report["generated_at"])
    return report if age < max_age else None


def _cached(symbol: str, max_age: timedelta) -> dict | None:
    """This instance's /tmp, then the reports shipped with the app, then Blob, which
    outlives the redeploy that every data refresh triggers."""
    for folder in (LIVE, PRECOMPUTED):
        f = folder / f"{symbol}.json"
        if f.exists() and (report := _fresh(json.loads(f.read_text(encoding="utf-8")), max_age)):
            return report
    return _fresh(blobstore.load_report(symbol), max_age)


@app.get("/api/health")
def health(deep: bool = False) -> dict:
    out = {
        "ok": True,
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA", "local")[:7],  # which deploy answered
        "keys": env_summary(),  # counts, never the keys
        "blob": blobstore.enabled(),
    }
    if deep:
        out["blob_check"] = blobstore.check()
    return out


@app.get("/api/research/{symbol}")
def research(symbol: str, refresh: bool = False) -> StreamingResponse:
    """Newline-delimited JSON: one progress event per stage, then the report."""
    symbol = _symbol(symbol)
    cached = _cached(symbol, REFRESH_AFTER if refresh else FRESH)

    def events():
        if cached:
            yield (
                json.dumps({"stage": "done", "message": "From FINN's cache", "report": cached})
                + "\n"
            )
            return
        try:
            for event in engine.stream(
                symbol, refresh=refresh, save_dir=LIVE, budget_s=LIVE_BUDGET_S
            ):
                yield json.dumps(event, default=str) + "\n"
                if event["stage"] == "done":
                    blobstore.save_report(symbol, event["report"])
        except LookupError as exc:  # screener.in has no such company
            yield json.dumps({"stage": "error", "message": str(exc)}) + "\n"
        except Exception:  # noqa: BLE001 - the stream must end with a message, not a hang
            log.exception("research failed for %s", symbol)
            yield json.dumps({"stage": "error", "message": f"Research on {symbol} failed. "
                              "Try again in a minute."}) + "\n"  # fmt: skip

    return StreamingResponse(events(), media_type="application/x-ndjson")


class AskIn(BaseModel):
    symbol: str
    question: str = Field(min_length=3, max_length=MAX_QUESTION)
    context: str = Field("", max_length=600)


@app.post("/api/ask")
def ask_about(body: AskIn) -> AskAnswer:
    symbol = _symbol(body.symbol)
    conn = connect()
    try:
        return ask(conn, LLM.from_env(conn), symbol, body.question, body.context)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except AIUnavailable as exc:
        raise HTTPException(503, "Every model is busy right now. Try again in a minute.") from exc
    finally:
        conn.close()
