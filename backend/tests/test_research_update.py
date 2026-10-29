"""Reports keep up with their companies: finding missed calls, and rebuilding when behind."""

import json
import sqlite3
from datetime import UTC, date, datetime, timedelta

from finn.contracts import ResearchReport
from finn.research import update
from finn.research.gather import calls_to_fetch, same_call
from finn.research.update import Filed, changes, complete, newest_call, reason


def _report(symbol="MARUTI", calls=("Q4 FY26 call, 28 Apr 2026",), built="2026-10-29T08:00:00+00:00",
            promises=(), notes=(), calls_read=None):  # fmt: skip
    return ResearchReport.model_validate({
        "symbol": symbol, "name": symbol, "basis": "consolidated", "generated_at": built,
        "snapshot": {"about": None, "latest_quarter": "Q1 FY27", "revenue": None, "revenue_yoy": None,
                     "net_profit": None, "net_profit_yoy": None, "ebitda_margin": None},
        "narrative": None, "promises": [
            {"id": f"P{i}", "metric": m, "period": "FY26", "target": None, "statement": m,
             "said": {"quote": "q", "source": "s", "url": "u"}, "verdict": v, "verdict_by": "code"}
            for i, (m, v) in enumerate(promises, 1)],
        "cash": {"applicable": False, "reason": "bank"}, "bull": [], "bear": [], "notes": list(notes),
        "documents": [{"label": c, "kind": "transcript", "url": "u", "pages": 1} for c in calls],
        "stats": {"calls_read": len(calls) if calls_read is None else calls_read, "claims_found": 0,
                  "quotes_verified": 0, "quotes_dropped": 0, "graded_by_code": 0, "graded_by_model": 0,
                  "ai_calls": 0, "cached_calls": 0, "models": [], "seconds": 1},
    })  # fmt: skip


NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)


def test_missed_calls_are_taken_from_nse_one_per_call():
    # Maruti on 29 Oct 2026: screener.in had only April readable; NSE lists four transcripts.
    # May's is April's call, filed days later, so it is not taken twice.
    assert same_call("2026-04", "2026-05")
    assert calls_to_fetch(["2026-04"], ["2026-08", "2026-05", "2026-02", "2025-11"]) == [
        "2026-08", "2026-02", "2025-11"]  # fmt: skip
    # With four recent calls held, nothing older is fetched.
    assert calls_to_fetch(["2026-08", "2026-05", "2026-02", "2025-11"], ["2025-08"]) == []
    assert calls_to_fetch(["2026-07", "2026-04", "2026-01", "2025-10"], ["2026-10"]) == ["2026-10"]


def test_newest_call_is_read_from_its_label():
    assert (
        str(newest_call(_report(calls=("Q2 FY27 call, 21 Oct 2026", "Q1 FY27 call, 22 Jul 2026"))))
        == "2026-10-21"
    )
    assert str(newest_call(_report(calls=("Investor call, Aug 2026",)))) == "2026-08-15"
    assert newest_call(_report(calls=())) is None


def test_a_later_call_or_settled_results_put_a_report_behind():
    r = _report(calls=("Q2 FY27 call, 21 Oct 2026",))
    same = Filed(
        "nse:1", "2026-10-27T18:00:00+05:30", "Transcript of the earnings call", "earnings_call"
    )
    assert reason(r, [same], NOW) is None  # the 21 Oct call's own transcript, filed six days on
    later = Filed(
        "nse:2",
        "2027-01-25T18:00:00+05:30",
        "informed the Exchange about Transcript",
        "earnings_call",
    )
    assert reason(r, [same, later], datetime(2027, 1, 26, tzinfo=UTC))[0] == "transcript:nse:2"

    results = Filed("nse:3", "2026-11-01T16:00:00+05:30", "Outcome of board meeting", "results")
    assert reason(r, [results], NOW)[0] == "results:nse:3"
    assert (
        reason(r, [results], datetime(2026, 11, 1, 12, 0, tzinfo=UTC)) is None
    )  # screener.in may lag
    # For a research pick, NSE's own wording decides; an intimation is not the results.
    notice = Filed(
        "nse:4",
        "2026-11-01T16:00:00+05:30",
        "Intimation of board meeting to consider financial results",
    )
    assert reason(r, [notice], NOW) is None
    out = Filed("nse:5", "2026-11-01T16:00:00+05:30", "Financial Result Updates")
    assert reason(r, [out], NOW)[0] == "results:nse:5"


def test_changes_say_what_a_rebuild_did():
    old = _report(promises=[("Revenue", "pending"), ("Margin", "on_track")])
    new = _report(calls=("Q2 FY27 call, 27 Oct 2026", "Q4 FY26 call, 28 Apr 2026"),
                  promises=[("Revenue", "missed"), ("Margin", "on_track"), ("Capex", "pending")])  # fmt: skip
    assert changes(old, new) == [
        "Now reads the Q2 FY27 call, 27 Oct 2026.",
        "1 promise newly graded: Revenue missed.",
        "1 new promise from the latest calls.",
    ]


def test_an_incomplete_or_thinner_rebuild_never_replaces_a_report():
    old = _report(calls=("a 1 Jan 2026", "b 1 Oct 2025"), promises=[("Revenue", "pending")])
    assert complete(
        old, _report(calls=("c 1 Apr 2026", "a 1 Jan 2026"), promises=[("Revenue", "met")])
    )
    busy = _report(
        promises=[("Revenue", "unclear")], notes=["The reasoning model was unavailable: ..."]
    )
    assert not complete(old, busy)
    assert not complete(old, _report(calls=("c 1 Apr 2026",), promises=[("Revenue", "met")]))


def test_run_rebuilds_up_to_the_limit_and_marks_the_rest(tmp_path, monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    for s in ("ADANIENT", "MARUTI"):
        (tmp_path / f"{s}.json").write_text(
            _report(s, promises=[("Revenue", "pending")]).model_dump_json()
        )
    (tmp_path / "index.json").write_text("{}")
    later = Filed("nse:9", "2026-10-28T20:00:00+05:30", "Transcript", "earnings_call")
    monkeypatch.setattr(update, "_filed", lambda conn, s: [later])
    monkeypatch.setattr(update, "DATA_DIR", tmp_path)
    built = []

    def fake_research(symbol, refresh, save_dir):
        built.append(symbol)
        return _report(symbol, calls=("Q2 FY27 call, 27 Oct 2026", "Q4 FY26 call, 28 Apr 2026"),
                       promises=[("Revenue", "missed")], built="2026-11-03T12:00:00+00:00")  # fmt: skip

    monkeypatch.setattr(update, "research", fake_research)
    stats = update.run(conn, tmp_path, limit=1)
    assert built == ["ADANIENT"] and stats["updated"] == ["ADANIENT"]
    a = json.loads((tmp_path / "ADANIENT.json").read_text())
    assert a["pending"] is None and a["changes"][0] == "Now reads the Q2 FY27 call, 27 Oct 2026."
    m = json.loads((tmp_path / "MARUTI.json").read_text())
    assert m["pending"] == "A new call transcript was filed on 28 Oct 2026."
    # The next run takes Maruti; Adani is current now, so it is not rebuilt again.
    stats = update.run(conn, tmp_path, limit=1)
    assert built == ["ADANIENT", "MARUTI"] and stats["behind"] == ["MARUTI"]


def test_a_holding_whose_newest_call_is_old_is_checked_on_nse_too(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE filings (id, symbol, filed_at, exchange_label, headline, attachment_url, category)"
    )
    asked = []

    def fake_nse(company, start, end):
        asked.append((company.symbol, start))
        return [{"id": "nse:7", "filed_at": f"{date.today() - timedelta(days=90)}T17:32:00+05:30", "exchange_label": "Con. Call Updates",
                 "headline": "informed the Exchange about Transcript", "attachment_url": "x.pdf"}]  # fmt: skip

    monkeypatch.setattr(update.filings, "fetch_nse", fake_nse)
    today = date.today()
    old = _report("MARUTI", calls=(f"Q4 FY26 call, {today - timedelta(days=184):%d %b %Y}",))
    filed = update._filed(conn, old)
    assert asked and asked[0][1] <= newest_call(old)  # looks back to the newest call it read
    assert reason(old, filed, datetime.now(UTC))[0] == "transcript:nse:7"  # filed after that call
    assert update._filed(conn, old) == []  # asked again within six hours: Push's filings only
    recent = _report("MARUTI", calls=(f"Q2 FY27 call, {today - timedelta(days=2):%d %b %Y}",))
    asked.clear()
    update._filed(conn, recent)
    assert not asked  # a recent call: Push's own filings are enough


def test_a_report_short_of_calls_takes_one_it_lacks():
    # Reliance read three calls; NSE has a fourth, older than the newest.
    r = _report(
        "RELIANCE",
        calls=(
            "Q1 FY27 call, 17 Jul 2026",
            "Q4 FY26 call, 24 Apr 2026",
            "Q2 FY26 call, 17 Oct 2025",
        ),
    )
    own = Filed(
        "nse:1", "2026-04-28T18:00:00+05:30", "Transcript", "earnings_call"
    )  # April's own transcript
    assert reason(r, [own], NOW) is None
    missing = Filed(
        "nse:2", "2026-01-20T18:00:00+05:30", "Transcript", "earnings_call"
    )  # January's call
    assert reason(r, [own, missing], NOW) == (
        "transcript:nse:2",
        "A call transcript filed on 20 Jan 2026 is not in this report.",
    )
    full = _report(
        "RELIANCE", calls=("a, 17 Jul 2026", "b, 24 Apr 2026", "c, 16 Jan 2026", "d, 17 Oct 2025")
    )
    assert (
        reason(full, [Filed("nse:3", "2025-07-20T18:00:00+05:30", "Transcript")], NOW) is None
    )  # older than four
