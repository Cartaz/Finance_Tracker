from __future__ import annotations

import pytest

from core.posting_policy import PostingPolicy
from core.tracking_policy import TrackingBoundaryPolicy, TrackingBoundaryStatus
from core.transport import TransportSerializer


def test_tracking_policy_centralizes_date_and_time_boundary_semantics() -> None:
    before = TrackingBoundaryPolicy.classify(
        tracking_start_date="2026-08-24",
        tracking_start_time="10:30:00",
        transaction_date="2026-08-23",
        transaction_time="23:59:59",
    )
    ambiguous = TrackingBoundaryPolicy.classify(
        tracking_start_date="2026-08-24",
        tracking_start_time="10:30:00",
        transaction_date="2026-08-24",
        transaction_time=None,
    )
    after = TrackingBoundaryPolicy.classify(
        tracking_start_date="2026-08-24",
        tracking_start_time="10:30:00",
        transaction_date="2026-08-24",
        transaction_time="10:30:01",
    )
    opening = TrackingBoundaryPolicy.classify(
        tracking_start_date="2026-08-24",
        tracking_start_time="10:30:00",
        transaction_date="2026-08-24",
        transaction_time="10:30:00",
        opening_balance=True,
    )

    assert before.status is TrackingBoundaryStatus.BEFORE_BOUNDARY
    assert ambiguous.status is TrackingBoundaryStatus.AMBIGUOUS
    assert after.status is TrackingBoundaryStatus.VALID
    assert opening.status is TrackingBoundaryStatus.VALID


def test_posting_policy_exposes_signed_amount_capabilities() -> None:
    assert PostingPolicy.allowed_kinds_for_amount(-1) == ("EXPENSE", "TRANSFER")
    assert PostingPolicy.allowed_kinds_for_amount(1) == (
        "INCOME",
        "REFUND",
        "TRANSFER",
    )
    assert PostingPolicy.allowed_kinds_for_amount(0) == ()


def test_posting_policy_owns_book_cash_flow_direction() -> None:
    assert PostingPolicy.book_cash_flow_direction("EXPENSE") == "OUTFLOW"
    assert PostingPolicy.book_cash_flow_direction("INCOME") == "INFLOW"
    assert PostingPolicy.book_cash_flow_direction("REFUND") == "INFLOW"
    assert PostingPolicy.book_cash_flow_direction("TRANSFER") == "TRANSFER"
    with pytest.raises(ValueError, match="unsupported posting kind"):
        PostingPolicy.book_cash_flow_direction("UNKNOWN")


def test_posting_policy_filters_counter_accounts() -> None:
    assert PostingPolicy.counter_is_eligible(
        "EXPENSE",
        source_account_id=1,
        source_currency="EUR",
        counter_account_id=2,
        counter_type="EXPENSE",
        counter_currency=None,
        counter_archived=False,
        counter_placeholder=False,
    )
    assert not PostingPolicy.counter_is_eligible(
        "TRANSFER",
        source_account_id=1,
        source_currency="EUR",
        counter_account_id=2,
        counter_type="ASSET",
        counter_currency="USD",
        counter_archived=False,
        counter_placeholder=False,
    )


def test_transport_serializer_stringifies_explicit_financial_integers() -> None:
    payload = TransportSerializer.serialize(
        {
            "amountMinor": 9_007_199_254_740_993,
            "savingRateBps": 1234,
            "count": 42,
        }
    )
    assert payload == {
        "amountMinor": "9007199254740993",
        "savingRateBps": "1234",
        "count": 42,
    }


def test_budget_transport_fields_are_explicit_financial_integers() -> None:
    payload = TransportSerializer.serialize(
        {
            "spentMinor": 9_007_199_254_740_993,
            "remainingMinor": -5,
            "totalBudgetMinor": 10,
            "totalSpentMinor": 6,
            "totalRemainingMinor": 4,
            "usageBps": 12_345,
        }
    )
    assert payload == {
        "spentMinor": "9007199254740993",
        "remainingMinor": "-5",
        "totalBudgetMinor": "10",
        "totalSpentMinor": "6",
        "totalRemainingMinor": "4",
        "usageBps": "12345",
    }
