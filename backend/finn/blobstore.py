"""Durable storage for live research, on Vercel Blob.

A live report is written to the server's /tmp, which a new instance or a redeploy wipes,
and the data refresh redeploys every 30 minutes. Without a durable copy, someone who
researched a ticker and came back an hour later would wait three minutes again.

Uses Vercel's own SDK, which reads BLOB_READ_WRITE_TOKEN; Vercel sets it when a Blob
store is connected to the project. With no token (local runs) this module does nothing,
and a storage failure never fails a request.
"""

from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

PREFIX = "research"


def enabled() -> bool:
    return bool(
        os.environ.get("BLOB_READ_WRITE_TOKEN") or os.environ.get("VERCEL_BLOB_READ_WRITE_TOKEN")
    )


def save_report(symbol: str, report: dict) -> None:
    if not enabled():
        return
    try:
        from vercel import blob

        blob.put(f"{PREFIX}/{symbol}.json", json.dumps(report).encode(), access="private",
                 content_type="application/json", overwrite=True)  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - the user already has their report
        log.warning("could not store %s in Blob: %s", symbol, exc)


def load_report(symbol: str) -> dict | None:
    if not enabled():
        return None
    try:
        from vercel import blob

        return json.loads(blob.get(f"{PREFIX}/{symbol}.json", access="private").content)
    except Exception as exc:  # noqa: BLE001 - not stored yet, or Blob is down: research live
        level = logging.INFO if type(exc).__name__ == "BlobNotFoundError" else logging.WARNING
        log.log(level, "no stored report for %s: %s: %s", symbol, type(exc).__name__, exc)
        return None


def check() -> str:
    """Write and read back a tiny file: 'ok', or the error, for the health endpoint."""
    if not enabled():
        return "no BLOB_READ_WRITE_TOKEN"
    try:
        from vercel import blob

        blob.put(
            "health/ping.txt", b"ok", access="private", content_type="text/plain", overwrite=True
        )
        body = blob.get("health/ping.txt", access="private", use_cache=False).content
        return "ok" if body == b"ok" else f"read back {body[:20]!r}"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return f"{type(exc).__name__}: {str(exc)[:300]}"
