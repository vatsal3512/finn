"""Grouping: one event shows once, with every distinct card merged onto its lead."""

from finn import contracts as C
from finn.export import _merge_groups


def _filing(
    fid,
    score,
    cards,
    dup=None,
    group="NAZARA:management_change:2026-10-12",
    filed="2026-10-12T18:39:45+05:30",
):
    return C.Filing(id=fid, symbol="NAZARA", exchange="NSE", filed_at=filed, exchange_label="x", headline="x",
                    category="management_change", tier="must_see", classified_by="ai", rule=None, needs_ai=False,
                    text_quality="ok", attachment_url=None, source_url="u", cards=cards, score=score,
                    group_id=group, duplicate_of=dup)  # fmt: skip


def _people(*names):
    return C.PeopleCard(
        changes=[C.PersonChange(person=n, role="CFO", change="appointment") for n in names]
    )


def test_copies_merge_into_one_lead_with_people_deduplicated():
    original = _filing("nse:1", 118, [_people("Arun Agrawal")])
    copy = _filing("nse:2", 118, [_people("Arun Agrawal", "Rohit Sharma")], dup="nse:1")
    _merge_groups([copy, original])
    assert original.group_lead and not copy.group_lead
    assert copy.cards == []
    names = [c.person for card in original.cards for c in card.changes]
    assert names == ["Arun Agrawal", "Rohit Sharma"]  # Arun once, Rohit kept


def test_results_card_shown_once_per_quarter():
    card = C.ResultsCard(symbol="X", period_end="2026-09-30", period_label="Q2 FY27", basis="consolidated",
                         kind="standard", metrics=[], source="xbrl", check_note="", source_urls=[])  # fmt: skip
    a = _filing("nse:1", 120, [card], group="X:results:2026-10-27")
    b = _filing("nse:2", 60, [card], group="X:results:2026-10-27")
    _merge_groups([a, b])
    assert a.group_lead and len(a.cards) == 1 and b.cards == []


def test_separate_events_stay_separate():
    a = _filing("nse:1", 120, [], group="X:results:2026-10-27")
    b = _filing("nse:2", 45, [], group="X:dividend:2026-10-27")
    _merge_groups([a, b])
    assert a.group_lead and b.group_lead
