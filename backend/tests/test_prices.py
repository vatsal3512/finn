from datetime import UTC, date, datetime

import pandas as pd
import pytest

from finn.collectors.corp_actions import kind_of
from finn.collectors.prices import compute_metrics, last_settled


def _frame(volumes, closes=None):
    idx = pd.date_range("2026-09-01", periods=len(volumes), freq="B")
    closes = closes or [100.0] * len(volumes)
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


def test_volume_ratio_excludes_today_from_its_own_baseline():
    m = compute_metrics(_frame([1000] * 20 + [3000]), breaks={}, window=20)
    # Baseline is the previous 20 sessions (1000), so a 3000 day is exactly 3x.
    assert m["vol_ratio"].iloc[-1] == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("utc", "settled"),
    [
        (datetime(2026, 10, 29, 8, 4, tzinfo=UTC), date(2026, 10, 28)),  # 13:34 IST, market open
        (datetime(2026, 10, 29, 10, 31, tzinfo=UTC), date(2026, 10, 29)),  # 16:01 IST, closed
        (
            datetime(2026, 10, 28, 19, 0, tzinfo=UTC),
            date(2026, 10, 28),
        ),  # 00:30 IST, before the open
    ],
)
def test_a_session_counts_only_once_it_has_closed(utc, settled):
    assert last_settled(utc) == settled


def test_no_ratio_until_the_baseline_is_full():
    m = compute_metrics(_frame([1000] * 10), breaks={}, window=20)
    assert m["vol_ratio"].isna().all()


def test_returns_and_corporate_action_flag():
    df = _frame([1000] * 3, closes=[100.0, 110.0, 38.5])
    m = compute_metrics(df, breaks={df.index[2].date().isoformat(): "demerger"}, window=2)
    assert m["ret_pct"].iloc[1] == pytest.approx(10.0)
    assert m["corp_action"].iloc[2] == "demerger"  # the -65% day is marked, not alerted
    assert m["corp_action"].iloc[1] is None


@pytest.mark.parametrize(
    ("subject", "kind"),
    [
        ("Demerger", "demerger"),
        ("Bonus 1:1", "bonus"),
        ("Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "split"),
        ("Bonus 1:1 And Face Value Split", "bonus"),
        ("Interim Dividend - Rs 11 Per Share", "dividend"),
        ("Rights 2:25 @ Premium Rs 17/-", "rights"),
        ("Annual General Meeting", "other"),
    ],
)
def test_corporate_action_kinds(subject, kind):
    assert kind_of(subject) == kind
