from __future__ import annotations

from decimal import Decimal, InvalidOperation

from core.errors import LoanError

_MAX_ANNUAL_RATE_BPS = 100_000


def parse_annual_rate_bps(value: object) -> int:
    """Parse an unsigned annual percentage into exact integer basis points."""
    if isinstance(value, (bool, int, float)):
        raise LoanError("annual rate must be entered as unsigned percentage text")
    if not isinstance(value, str):
        raise LoanError("annual rate must be entered as unsigned percentage text")
    text = value.strip().replace(" ", "")
    if not text or text[0] in "+-":
        raise LoanError("annual rate must be unsigned")
    if "," in text and "." in text:
        raise LoanError("annual rate contains ambiguous decimal separators")
    normalized = text.replace(",", ".")
    try:
        percent = Decimal(normalized)
    except InvalidOperation as exc:
        raise LoanError("invalid annual rate") from exc
    if not percent.is_finite() or percent < 0:
        raise LoanError("annual rate must be non-negative")
    bps = percent * Decimal(100)
    if bps != bps.to_integral_value():
        raise LoanError("annual rate supports at most two decimal places")
    parsed = int(bps)
    if parsed > _MAX_ANNUAL_RATE_BPS:
        raise LoanError("annual rate cannot exceed 1000%")
    return parsed
