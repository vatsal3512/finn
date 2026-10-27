"""An ordered pool of API keys with per-model cooldowns.

Keys are tried in a fixed order (decision D9): FINN uses the first key until it hits a
limit, rests it, and moves to the next. Cooldowns are stored in SQLite, so a scheduled
run and a manual run on the same machine respect each other.

Two kinds of limit are told apart:
- A per-minute limit rests the key for about a minute.
- A daily quota rests it until Google resets quotas at midnight Pacific time.

Secrets never leave this module: logs, the database and errors only see aliases such as
"gemini-3".
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass(frozen=True)
class Key:
    provider: str
    alias: str
    secret: str = field(repr=False)


def keys_from_env(provider: str, var: str) -> list[Key]:
    """Read keys from an environment variable holding a comma- or newline-separated list."""
    raw = os.environ.get(var, "")
    secrets = [s.strip() for s in raw.replace("\n", ",").split(",") if s.strip()]
    return [Key(provider, f"{provider}-{i + 1}", s) for i, s in enumerate(secrets)]


def seconds_until_quota_reset(now: datetime | None = None) -> float:
    now = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
    return (reset - now).total_seconds()


class KeyPool:
    def __init__(self, conn: sqlite3.Connection, keys: list[Key], min_interval: float):
        self.conn = conn
        self.keys = keys
        self.min_interval = min_interval  # pacing per key and model, below the RPM cap
        self._last: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def __bool__(self) -> bool:
        return bool(self.keys)

    def _cooldown_until(self, key: Key, model: str) -> float:
        row = self.conn.execute(
            "SELECT cooldown_until FROM ai_key_state WHERE provider = ? AND key_alias = ? AND model = ?",
            (key.provider, key.alias, model),
        ).fetchone()
        return row[0] if row else 0.0

    def available(self, model: str) -> list[Key]:
        now = time.time()
        return [k for k in self.keys if self._cooldown_until(k, model) <= now]

    def rest(self, key: Key, model: str, seconds: float, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO ai_key_state (provider, key_alias, model, cooldown_until, reason) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (provider, key_alias, model) DO UPDATE SET "
            "cooldown_until = excluded.cooldown_until, reason = excluded.reason",
            (key.provider, key.alias, model, time.time() + seconds, reason[:200]),
        )
        self.conn.commit()

    def pace(self, key: Key, model: str) -> None:
        with self._lock:
            slot = (key.alias, model)
            wait = self._last.get(slot, 0.0) + self.min_interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[slot] = time.monotonic()
