from __future__ import annotations

import pytest

from core.errors import LoanError
from core.rates import parse_annual_rate_bps


def test_parse_annual_rate_bps_is_exact_and_locale_tolerant() -> None:
    assert parse_annual_rate_bps("0") == 0
    assert parse_annual_rate_bps("5,25") == 525
    assert parse_annual_rate_bps("5.25") == 525
    assert parse_annual_rate_bps(" 12,00 ") == 1200


@pytest.mark.parametrize("value", ["+5", "-5", "5,251", "5,2.5", "nan", "inf"])
def test_parse_annual_rate_bps_rejects_ambiguous_or_inexact_values(value: str) -> None:
    with pytest.raises(LoanError):
        parse_annual_rate_bps(value)


@pytest.mark.parametrize("value", [5, 5.25, True, None])
def test_parse_annual_rate_bps_rejects_non_text_transport_values(value: object) -> None:
    with pytest.raises(LoanError):
        parse_annual_rate_bps(value)
