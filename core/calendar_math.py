"""Calendar arithmetic shared by recurring schedules and loan installments."""

from __future__ import annotations

import calendar
from datetime import date


def shift_months(current: date, months: int, anchor_day: int) -> date:
    """Move ``months`` calendar months, landing on ``anchor_day`` or month end.

    The anchor day is kept separately from ``current`` so a series anchored on
    the 31st returns to the 31st after passing through shorter months.
    """
    month_index = current.year * 12 + current.month - 1 + months
    year, zero_month = divmod(month_index, 12)
    month = zero_month + 1
    return date(year, month, min(anchor_day, calendar.monthrange(year, month)[1]))
