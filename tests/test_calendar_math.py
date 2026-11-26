from __future__ import annotations

from datetime import date

import pytest

from core.calendar_math import shift_months


@pytest.mark.parametrize(
    ("current", "months", "anchor_day", "expected"),
    [
        (date(2026, 1, 31), 1, 31, date(2026, 2, 28)),
        (date(2026, 2, 28), 1, 31, date(2026, 3, 31)),  # returns to the anchor
        (date(2024, 1, 31), 1, 31, date(2024, 2, 29)),
        (date(2026, 11, 15), 3, 15, date(2027, 2, 15)),
        (date(2026, 1, 31), 0, 31, date(2026, 1, 31)),
        (date(2026, 3, 31), -1, 31, date(2026, 2, 28)),
    ],
)
def test_shift_months_clamps_and_keeps_anchor(current, months, anchor_day, expected) -> None:
    assert shift_months(current, months, anchor_day) == expected
