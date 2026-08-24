from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum


class TrackingBoundaryStatus(StrEnum):
    VALID = "VALID"
    BEFORE_BOUNDARY = "BEFORE_BOUNDARY"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class TrackingBoundaryResult:
    status: TrackingBoundaryStatus

    @property
    def is_valid(self) -> bool:
        return self.status is TrackingBoundaryStatus.VALID


class TrackingBoundaryPolicy:
    """Canonical interpretation of account tracking boundaries.

    The policy is intentionally presentation-agnostic. Callers translate the
    result into their own domain error or workflow state, but must not
    reimplement the temporal rule.
    """

    @staticmethod
    def classify(
        *,
        tracking_start_date: str,
        tracking_start_time: str | None,
        transaction_date: str,
        transaction_time: str | None,
        opening_balance: bool = False,
    ) -> TrackingBoundaryResult:
        start_date = date.fromisoformat(tracking_start_date)
        posting_date = date.fromisoformat(transaction_date)

        if posting_date < start_date:
            return TrackingBoundaryResult(TrackingBoundaryStatus.BEFORE_BOUNDARY)
        if posting_date > start_date:
            return TrackingBoundaryResult(TrackingBoundaryStatus.VALID)

        if opening_balance and transaction_time == tracking_start_time:
            return TrackingBoundaryResult(TrackingBoundaryStatus.VALID)
        if tracking_start_time is None or transaction_time is None:
            return TrackingBoundaryResult(TrackingBoundaryStatus.AMBIGUOUS)

        start_time = time.fromisoformat(tracking_start_time)
        posting_time = time.fromisoformat(transaction_time)
        if posting_time < start_time:
            return TrackingBoundaryResult(TrackingBoundaryStatus.BEFORE_BOUNDARY)
        return TrackingBoundaryResult(TrackingBoundaryStatus.VALID)
