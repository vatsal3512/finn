"""The live API: symbols are validated, the cache is served first, and errors end the stream."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from finn import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "PRECOMPUTED", tmp_path / "pre")
    monkeypatch.setattr(api, "LIVE", tmp_path / "live")
    return TestClient(api.app)


def _write(folder, symbol, age):
    folder.mkdir(parents=True, exist_ok=True)
    when = (datetime.now(UTC) - age).isoformat()
    (folder / f"{symbol}.json").write_text(json.dumps({"symbol": symbol, "generated_at": when}))


def _events(resp):
    return [json.loads(line) for line in resp.text.splitlines() if line]


def test_bad_symbol_is_refused(client):
    assert client.get("/api/research/DROP%20TABLE").status_code == 422


def test_a_fresh_report_is_served_from_the_cache_without_any_work(client, tmp_path, monkeypatch):
    _write(tmp_path / "pre", "KAYNES", timedelta(days=1))
    monkeypatch.setattr(api.engine, "stream", lambda *a, **k: pytest.fail("should not research"))
    events = _events(client.get("/api/research/kaynes.ns"))
    assert events == [{"stage": "done", "message": "From FINN's cache",
                       "report": events[0]["report"]}]  # fmt: skip
    assert events[0]["report"]["symbol"] == "KAYNES"


def test_a_stale_report_is_researched_again_and_streamed(client, tmp_path, monkeypatch):
    _write(tmp_path / "pre", "KAYNES", timedelta(days=30))

    def fake_stream(symbol, refresh=False, save_dir=None, budget_s=None):
        yield {"stage": "gather", "message": "Collecting"}
        yield {"stage": "done", "message": "Done", "report": {"symbol": symbol}}

    monkeypatch.setattr(api.engine, "stream", fake_stream)
    assert [e["stage"] for e in _events(client.get("/api/research/KAYNES"))] == ["gather", "done"]


def test_a_failure_ends_the_stream_with_a_message(client, monkeypatch):
    def broken(symbol, refresh=False, save_dir=None, budget_s=None):
        yield {"stage": "gather", "message": "Collecting"}
        raise RuntimeError("boom")

    monkeypatch.setattr(api.engine, "stream", broken)
    events = _events(client.get("/api/research/NEWCO"))
    assert events[-1]["stage"] == "error" and "NEWCO" in events[-1]["message"]


def test_ask_validates_and_answers(client, monkeypatch):
    seen = {}

    def fake_ask(conn, llm, symbol, question, context=""):
        seen.update(symbol=symbol, question=question)
        return api.AskAnswer(symbol=symbol, question=question, addressed=True, answer="a",
                             calls=["Q1 FY27 call, Aug 2026"], asked_at="now")  # fmt: skip

    monkeypatch.setattr(api, "ask", fake_ask)
    r = client.post("/api/ask", json={"symbol": "mazdock", "question": "What about margins?"})
    assert r.status_code == 200 and seen == {"symbol": "MAZDOCK", "question": "What about margins?"}
    assert client.post("/api/ask", json={"symbol": "X", "question": "?"}).status_code == 422
