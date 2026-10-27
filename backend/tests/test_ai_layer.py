"""The AI client's routing, failover and caching, tested with fake backends: no keys, no cost."""

import pytest
from pydantic import BaseModel

from finn.ai import llm as L
from finn.ai.keys import Key, KeyPool
from finn.store import connect


class Answer(BaseModel):
    value: str


class FakeBackend:
    def __init__(self, provider, script, busy=()):
        self.provider = provider
        self.busy = set(busy)  # models over capacity for every key
        self.script = script  # alias -> list of outcomes: "ok", "rate", "daily", "bad_json", "transient", "busy"
        self.calls = []

    def call(self, key, model, thinking, system, prompt, images, schema, max_output_tokens):
        self.calls.append((key.alias, model, thinking, bool(images)))
        if model in self.busy:
            raise L.ModelBusy("503 high demand")
        outcome = self.script.get(key.alias, ["ok"]).pop(0) if self.script.get(key.alias) else "ok"
        if outcome == "rate":
            raise L.RateLimited("429 per minute", daily=False)
        if outcome == "daily":
            raise L.RateLimited("429 requests per day", daily=True)
        if outcome == "transient":
            raise L.Transient("500")
        if outcome == "busy":
            raise L.ModelBusy("503 high demand")
        if outcome == "bad_json":
            return L.Reply("not json")
        return L.Reply(f'{{"value": "{key.alias}"}}', 10, 5)


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setattr(KeyPool, "pace", lambda self, key, model: None)
    L.LLM._busy_until.clear()  # shared across the process, so reset between tests


def _llm(tmp_path, gemini_script=None, groq_script=None, n_gemini=3, n_groq=1, busy=()):
    conn = connect(tmp_path / "t.db")
    g = FakeBackend("gemini", gemini_script or {}, busy)
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
    assert g.calls[1][1:3] == (L.FLASH_PEERS[0], "high")


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


FLASH, LITE = L.GEMINI_ROUTES[L.Tier.FLASH].model, L.GEMINI_ROUTES[L.Tier.LITE].model
PEERS = L.GEMINI_ROUTES[L.Tier.FLASH].models


def test_a_busy_model_hands_over_to_its_peer_after_two_keys_say_so(tmp_path):
    # 28 Oct 2026: gemini-3.8-flash returned 503 on every key while 3.6 answered in 2s.
    llm, g, q, _ = _llm(tmp_path, n_gemini=4, busy={FLASH})
    assert ask(llm, tier=L.Tier.FLASH).value == "gemini-1"
    assert [c[:2] for c in g.calls] == [
        ("gemini-1", FLASH),
        ("gemini-2", FLASH),
        ("gemini-1", PEERS[1]),
    ]
    assert llm.last_model == PEERS[1] and llm.stats["peers"] == 1 and q.calls == []
    # While the model rests, the next Flash task goes straight to the peer.
    g.calls.clear()
    ask(llm, "next", tier=L.Tier.FLASH)
    assert [c[1] for c in g.calls] == [PEERS[1]]


def test_all_flash_peers_busy_falls_back_to_groq(tmp_path):
    llm, g, q, conn = _llm(tmp_path, busy=set(PEERS))
    assert ask(llm, tier=L.Tier.FLASH).value == "groq-1"
    assert llm.stats["fallbacks"] == 1
    assert conn.execute("SELECT degraded FROM ai_cache").fetchone()[0] == 1


def test_busy_flash_steps_down_to_lite_for_images_and_is_not_cached(tmp_path):
    llm, g, q, conn = _llm(tmp_path, busy=set(PEERS))
    assert ask(llm, images=[b"png"], tier=L.Tier.FLASH).value == "gemini-1"
    assert g.calls[-1][1] == LITE and q.calls == []
    assert llm.stats["step_downs"] == 1 and llm.last_model == LITE
    assert conn.execute("SELECT COUNT(*) FROM ai_cache").fetchone()[0] == 0


def test_groq_never_gets_a_prompt_over_its_limit(tmp_path):
    llm, g, q, _ = _llm(tmp_path, busy=set(PEERS))
    long_prompt = "word " * 8000  # about 10K tokens: a transcript is 13K to 41K
    assert ask(llm, long_prompt, tier=L.Tier.FLASH).value == "gemini-1"
    assert q.calls == [] and llm.last_model == LITE


def test_lite_tasks_have_no_step_down(tmp_path):
    llm, g, q, _ = _llm(tmp_path, busy={LITE})
    assert ask(llm, tier=L.Tier.LITE).value == "groq-1"
    assert all(c[1] == LITE for c in g.calls) and len(g.calls) == 2


def test_last_model_is_reported_from_the_cache_too(tmp_path):
    llm, _, _, _ = _llm(tmp_path, {f"gemini-{i}": ["daily"] for i in (1, 2, 3)})
    ask(llm, "same")
    llm.last_model = None
    ask(llm, "same")
    assert llm.last_model == L.GROQ_MODEL


def test_a_slow_failure_marks_the_model_busy_at_once(tmp_path):
    class SlowBusy(FakeBackend):
        def call(self, key, model, *args):
            if model == FLASH:
                self.calls.append((key.alias, model))
                raise L.ModelBusy("504 deadline exceeded", slow=True)
            return super().call(key, model, *args)

    llm, _, _, _ = _llm(tmp_path, n_gemini=4)
    llm.gemini = SlowBusy("gemini", {})
    assert ask(llm, tier=L.Tier.FLASH).value == "gemini-1"
    assert [c for c in llm.gemini.calls if c[1] == FLASH] == [("gemini-1", FLASH)]


def test_busy_state_is_shared_between_clients(tmp_path):
    first, _, _, _ = _llm(tmp_path, busy={FLASH})
    ask(first, tier=L.Tier.FLASH)
    second, g2, _, _ = _llm(tmp_path / "other", busy=set())
    ask(second, "fresh", tier=L.Tier.FLASH)
    assert [c[1] for c in g2.calls] == [PEERS[1]]  # skipped FLASH without trying it
