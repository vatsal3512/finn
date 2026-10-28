import json

from finn import export
from finn.contracts import Filings, Meta, Portfolio
from finn.store import Run, connect, upsert


def test_upsert_is_idempotent_and_updates(tmp_path):
    conn = connect(tmp_path / "t.db")
    row = {"symbol": "X", "ex_date": "2026-04-30", "subject": "Demerger", "kind": "demerger",
           "record_date": None, "source_url": "u", "fetched_at": "t1"}  # fmt: skip
    key = ("symbol", "ex_date", "subject")
    upsert(conn, "corp_actions", [row], key)
    upsert(conn, "corp_actions", [{**row, "fetched_at": "t2"}], key)
    rows = conn.execute("SELECT fetched_at FROM corp_actions").fetchall()
    assert [r["fetched_at"] for r in rows] == ["t2"]


def test_run_records_failure(tmp_path):
    conn = connect(tmp_path / "t.db")
    try:
        with Run(conn, "test") as run:
            run.stats["step"] = 1
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    r = conn.execute("SELECT ok, stats FROM runs").fetchone()
    assert r["ok"] == 0 and "boom" in json.loads(r["stats"])["error"]


def test_export_matches_contract(tmp_path):
    conn = connect(tmp_path / "t.db")
    upsert(conn, "prices", [{"symbol": "HDFCBANK", "date": "2026-10-27", "open": 1, "high": 1, "low": 1,
           "close": 680.2, "volume": 10, "ret_pct": -1.1, "vol_ratio": 2.0, "corp_action": None,
           "source_url": "u", "fetched_at": "t"}], ("symbol", "date"))  # fmt: skip
    upsert(conn, "filings", [{"id": "nse:1", "symbol": "HDFCBANK", "exchange": "NSE",
           "filed_at": "2099-01-01T08:00:00+05:30", "exchange_label": "Change in Management",
           "headline": "new MD and CEO", "category": "management_change", "tier": "must_see",
           "classified_by": "rule", "rule": "management", "needs_ai": 1, "source_url": "u",
           "fetched_at": "t"}], ("id",))  # fmt: skip
    counts = export.run(conn, out_dir=tmp_path)
    portfolio = Portfolio.model_validate_json((tmp_path / "portfolio.json").read_text())
    filings = Filings.model_validate_json((tmp_path / "filings.json").read_text())
    meta = Meta.model_validate_json((tmp_path / "meta.json").read_text())
    hdfc = next(h for h in portfolio.holdings if h.symbol == "HDFCBANK")
    assert hdfc.close == 680.2 and hdfc.vol_ratio == 2.0
    assert filings.filings[0].tier == "must_see" and counts["must_see"] == 1
    assert meta.alert_defaults.volume_multiple == 2.0
    schema = json.loads((tmp_path / "schema.json").read_text())
    assert set(schema["properties"]) == {
        "portfolio", "filings", "meta", "research_report", "research_index", "ask",
    }  # fmt: skip
    assert "ResultsCard" in schema["$defs"] and "Guidance" in schema["$defs"]
