"""SQLite store: one file, no server, every row traceable to its source.

Why SQLite: the whole dataset is a few hundred MB at most, it needs no hosting, and the
file can be cached between scheduled runs. Every table carries `source_url` and
`fetched_at`, so any number the app shows can be traced back to where it came from.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from finn.config import DB_PATH

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    symbol        TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    sector        TEXT,
    size          TEXT,
    role          TEXT,              -- portfolio | research | adhoc
    bse_code      TEXT,
    screener_url  TEXT,
    is_bank       INTEGER,           -- results card needs a bank variant
    updated_at    TEXT NOT NULL
);

-- End-of-day prices with the two numbers alerts are judged on.
CREATE TABLE IF NOT EXISTS prices (
    symbol       TEXT NOT NULL,
    date         TEXT NOT NULL,      -- trading day, YYYY-MM-DD
    open         REAL, high REAL, low REAL,
    close        REAL NOT NULL,
    volume       INTEGER,
    ret_pct      REAL,               -- close-to-close move, %
    vol_ratio    REAL,               -- volume / mean of the previous 20 sessions
    corp_action  TEXT,               -- set on ex-dates of demergers, splits, bonuses
    source_url   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE TABLE IF NOT EXISTS corp_actions (
    symbol       TEXT NOT NULL,
    ex_date      TEXT NOT NULL,
    subject      TEXT NOT NULL,
    kind         TEXT NOT NULL,      -- demerger | split | bonus | rights | dividend | ...
    record_date  TEXT,
    source_url   TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (symbol, ex_date, subject)
);

-- Exchange announcements. `category` and `tier` come from rules when the rules are sure,
-- and are left for the AI step (needs_ai = 1) when they are not.
CREATE TABLE IF NOT EXISTS filings (
    id              TEXT PRIMARY KEY,   -- nse:<seq_id> or bse:<news_id>
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    filed_at        TEXT NOT NULL,      -- ISO 8601 with +05:30
    exchange_label  TEXT,               -- the exchange's own subject line, often vague
    headline        TEXT,
    attachment_url  TEXT,
    attachment_kind TEXT,               -- pdf | zip | none | other
    text_path       TEXT,               -- extracted text, relative to data/
    pdf_path        TEXT,               -- kept only when the text layer is unusable
    n_pages         INTEGER,
    text_quality    TEXT,               -- ok | garbled | no_text | not_fetched | failed
    category        TEXT,
    tier            TEXT,               -- must_see | glance | routine
    classified_by   TEXT,               -- rule | ai
    rule            TEXT,               -- which rule fired, for auditability
    needs_ai        INTEGER NOT NULL DEFAULT 0,
    source_url      TEXT NOT NULL,
    fetched_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS filings_by_symbol_time ON filings (symbol, filed_at);

-- Primary documents for research: transcripts, annual reports, results PDFs.
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,     -- sha1 of the URL
    symbol        TEXT NOT NULL,
    kind          TEXT NOT NULL,        -- transcript | annual_report | presentation | results
    period        TEXT,                 -- e.g. 2026-07 for a call, 2026 for a report
    title         TEXT,
    url           TEXT NOT NULL,
    text_path     TEXT,
    n_pages       INTEGER,
    text_quality  TEXT,
    sections      TEXT,                 -- JSON: section name -> page numbers
    source_url    TEXT NOT NULL,        -- the page that listed the document
    fetched_at    TEXT
);
CREATE INDEX IF NOT EXISTS documents_by_symbol ON documents (symbol, kind, period);

-- Standardised financial tables in long form: one row per line item per period.
CREATE TABLE IF NOT EXISTS financials (
    symbol      TEXT NOT NULL,
    basis       TEXT NOT NULL,          -- consolidated | standalone
    statement   TEXT NOT NULL,          -- quarters | profit_loss | balance_sheet | cash_flow | ratios
    period      TEXT NOT NULL,          -- YYYY-MM or TTM
    line_item   TEXT NOT NULL,
    value       REAL,
    raw         TEXT,
    source_url  TEXT NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (symbol, basis, statement, period, line_item)
);

-- One row per pipeline run, so failures and coverage are visible after the fact.
CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    command      TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    ok           INTEGER,
    stats        TEXT
);

-- ---------------------------------------------------------------- AI layer

-- Every model answer, keyed by task + prompt version + input hash, so nothing is paid
-- for twice. The key ignores which model answered, so a fallback answer is reused too;
-- `degraded` marks answers from a fallback model, which can be upgraded later.
CREATE TABLE IF NOT EXISTS ai_cache (
    key          TEXT PRIMARY KEY,
    task         TEXT NOT NULL,
    model        TEXT NOT NULL,
    degraded     INTEGER NOT NULL DEFAULT 0,
    response     TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

-- One row per real API call: the evidence for what the AI layer costs.
CREATE TABLE IF NOT EXISTS ai_usage (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    at             TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    key_alias      TEXT NOT NULL,        -- never the key itself
    task           TEXT NOT NULL,
    ok             INTEGER NOT NULL,
    input_tokens   INTEGER,
    output_tokens  INTEGER,
    thinking_tokens INTEGER,
    latency_ms     INTEGER,
    error          TEXT
);

-- Keys resting after a rate limit, so separate runs respect each other's cooldowns.
CREATE TABLE IF NOT EXISTS ai_key_state (
    provider        TEXT NOT NULL,
    key_alias       TEXT NOT NULL,
    model           TEXT NOT NULL,
    cooldown_until  REAL NOT NULL,       -- unix time
    reason          TEXT,
    PRIMARY KEY (provider, key_alias, model)
);

-- What the AI concluded about a filing. Kept apart from `filings` so collectors and
-- enrichment never overwrite each other.
CREATE TABLE IF NOT EXISTS filing_insights (
    filing_id        TEXT PRIMARY KEY,
    category         TEXT,
    tier             TEXT,
    title            TEXT,               -- short plain-English headline
    summary          TEXT,               -- what happened, one sentence
    why_it_matters   TEXT,
    sentiment        TEXT,
    amount_inr_crore REAL,
    model            TEXT,
    prompt_version   TEXT,
    created_at       TEXT NOT NULL
);

-- Headline numbers for a quarter, with where they came from and whether they checked out.
CREATE TABLE IF NOT EXISTS results_cards (
    symbol       TEXT NOT NULL,
    period_end   TEXT NOT NULL,          -- YYYY-MM-DD
    basis        TEXT,                   -- consolidated | standalone
    kind         TEXT NOT NULL,          -- standard | bank
    card         TEXT NOT NULL,          -- JSON, see contracts.ResultsCard
    source       TEXT NOT NULL,          -- xbrl | filing_text | filing_image | screener
    verified     INTEGER,                -- 1 matched screener.in, 0 mismatch, NULL not checkable
    created_at   TEXT NOT NULL,
    PRIMARY KEY (symbol, period_end)
);

-- People joining or leaving, with the bio taken from the filing's own profile section.
CREATE TABLE IF NOT EXISTS people_cards (
    filing_id    TEXT PRIMARY KEY,
    symbol       TEXT NOT NULL,
    card         TEXT NOT NULL,          -- JSON, see contracts.PeopleCard
    created_at   TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def upsert(
    conn: sqlite3.Connection,
    table: str,
    rows: Iterable[Mapping[str, Any]],
    key: tuple[str, ...],
) -> int:
    """Insert rows, or update every non-key column when the key already exists.

    Column names come from code, never from fetched data, so building the SQL from them
    is safe.
    """
    rows = list(rows)
    if not rows:
        return 0
    cols = list(rows[0].keys())
    updates = [c for c in cols if c not in key]
    sql = (
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
        f"ON CONFLICT ({', '.join(key)}) DO "
        + (
            f"UPDATE SET {', '.join(f'{c}=excluded.{c}' for c in updates)}"
            if updates
            else "NOTHING"
        )
    )
    conn.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
    return len(rows)


class Run:
    """Context manager that records a pipeline run and its stats in the runs table."""

    def __init__(self, conn: sqlite3.Connection, command: str):
        self.conn, self.command, self.stats = conn, command, {}

    def __enter__(self) -> Run:
        cur = self.conn.execute(
            "INSERT INTO runs (command, started_at) VALUES (?, ?)", (self.command, now_iso())
        )
        self.id = cur.lastrowid
        self.conn.commit()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.stats["error"] = f"{exc_type.__name__}: {exc}"
        self.conn.execute(
            "UPDATE runs SET finished_at = ?, ok = ?, stats = ? WHERE id = ?",
            (now_iso(), int(exc is None), json.dumps(self.stats, default=str), self.id),
        )
        self.conn.commit()
