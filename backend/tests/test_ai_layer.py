"""The AI client's routing, failover and caching, tested with fake backends: no keys, no cost."""

import pytest
from pydantic import BaseModel

from finn.ai import llm as L
from finn.ai.keys import Key, KeyPool
from finn.store import connect


class Answer(BaseModel):
    value: str


class FakeBackend:
    def __init__(self, provider, script):
        self.provider = provider
        self.script = (
            script  # alias -> list of outcomes: "ok", "rate", "daily", "bad_json", "transient"
        )
        self.calls = []

    def call(self, key, model, thinking, system, prompt, images, schema, max_output_tokens):
        self.calls.append((key.alias, model, thinking, bool(images)))
        outcome = self.script.get(key.alias, ["ok"]).pop(0) if self.script.get(key.alias) else "ok"
        if outcome == "rate":
            raise L.RateLimited("429 per minute", daily=False)
        if outcome == "daily":
            raise L.RateLimited("429 requests per day", daily=True)
        if outcome == "transient":
            raise L.Transient("503")
        if outcome == "bad_json":
            return L.Reply("not json")
        return L.Reply(f'{{"value": "{key.alias}"}}', 10, 5)


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setattr(KeyPool, "pace", lambda self, key, model: None)


def _llm(tmp_path, gemini_script=None, groq_script=None, n_gemini=3, n_groq=1):
    conn = connect(tmp_path / "t.db")
    g = FakeBackend("gemini", gemini_script or {})
    q = FakeBackend("groq", groq_script or {})
    llm = L.LLM(
        conn,
        [Key("gemini", f"gemini-{i + 1}", f"g{i}") for i in range(n_gemini)],
        [Key("groq", f"groq-{i + 1}", f"q{i}") for i in range(n_groq)],
        gemini=g,
        groq=q,
    )
    return llm, g, q, conn


def ask(llm, prompt="p", images=(), tier=L.Tier.LITE):
    return llm.json("t", tier, prompt, Answer, system="s", version="v1", images=images)


def test_routes_by_tier(tmp_path):
    llm, g, _, _ = _llm(tmp_path)
    ask(llm, "a", tier=L.Tier.LITE)
    ask(llm, "b", tier=L.Tier.REASON)
    assert g.calls[0][1:3] == ("gemini-3.5-flash-lite", "minimal")
    assert g.calls[1][1:3] == ("gemini-3.8-flash", "high")


def test_keys_are_used_in_order_and_rested_on_limits(tmp_path):
    llm, g, _, conn = _llm(tmp_path, {"gemini-1": ["daily"], "gemini-2": ["rate"]})
    assert ask(llm).value == "gemini-3"
    assert [c[0] for c in g.calls] == ["gemini-1", "gemini-2", "gemini-3"]
    reasons = dict(conn.execute("SELECT key_alias, reason FROM ai_key_state").fetchall())
    assert reasons == {"gemini-1": "daily quota", "gemini-2": "per-minute limit"}
    # A rested key is skipped on the next call, without being tried again.
    g.calls.clear()
    ask(llm, "another prompt")
    assert [c[0] for c in g.calls] == ["gemini-3"]


def test_falls_back_to_groq_for_text_only(tmp_path):
    llm, g, q, conn = _llm(tmp_path, {f"gemini-{i}": ["daily"] for i in (1, 2, 3)})
    assert ask(llm).value == "groq-1"
    assert llm.stats["fallbacks"] == 1
    assert conn.execute("SELECT degraded FROM ai_cache").fetchone()[0] == 1


def test_image_tasks_never_go_to_groq(tmp_path):
    llm, _, q, _ = _llm(tmp_path, {f"gemini-{i}": ["daily"] for i in (1, 2, 3)})
    with pytest.raises(L.AIUnavailable):
        ask(llm, images=[b"png"])
    assert q.calls == []


def test_bad_json_is_retried_once_on_the_same_key(tmp_path):
    llm, g, _, _ = _llm(tmp_path, {"gemini-1": ["bad_json", "ok"]})
    assert ask(llm).value == "gemini-1"
    assert [c[0] for c in g.calls] == ["gemini-1", "gemini-1"]


def test_answers_are_cached(tmp_path):
    llm, g, _, conn = _llm(tmp_path)
    ask(llm, "same")
    ask(llm, "same")
    assert len(g.calls) == 1 and llm.stats["cache_hits"] == 1
    usage = conn.execute("SELECT COUNT(*), SUM(input_tokens) FROM ai_usage WHERE ok = 1").fetchone()
    assert tuple(usage) == (1, 10)


def test_cache_key_changes_with_version_and_images():
    base = L.cache_key("t", "v1", "s", "p", [])
    assert base != L.cache_key("t", "v2", "s", "p", [])
    assert base != L.cache_key("t", "v1", "s", "p", [b"img"])


def test_secrets_never_reach_the_database(tmp_path):
    llm, _, _, conn = _llm(tmp_path, {"gemini-1": ["daily"]})
    ask(llm)
    dump = "\n".join(
        str(tuple(r))
        for t in ("ai_usage", "ai_key_state", "ai_cache")
        for r in conn.execute(f"SELECT * FROM {t}")
    )
    assert "g0" not in dump and "q0" not in dump


def test_quota_reset_is_midnight_pacific():
    from datetime import datetime

    from finn.ai.keys import PACIFIC, seconds_until_quota_reset

    assert 0 < seconds_until_quota_reset(datetime(2026, 10, 27, 23, 0, tzinfo=PACIFIC)) <= 3700
