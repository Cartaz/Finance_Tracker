from __future__ import annotations

from collections import defaultdict
from datetime import date

from core.errors import ForecastError, FxRateMissingError
from core.fx_service import FxService
from core.scheduled_transaction_service import ScheduledTransactionService

_GRANULARITIES = {"DAY", "MONTH", "YEAR"}
_MAX_HORIZON_DAYS = 3660
_MAX_OCCURRENCES = 10_000


class ForecastService:
    """Build deterministic read-only forecasts from canonical scheduled templates."""

    def __init__(
        self,
        scheduled: ScheduledTransactionService,
        fx: FxService,
    ) -> None:
        self._scheduled = scheduled
        self._fx = fx

    def cash_flow_forecast(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        granularity: str = "MONTH",
    ) -> dict[str, object]:
        start = self._parse_date(start_date, "start_date")
        end = self._parse_date(end_date, "end_date")
        if end < start:
            raise ForecastError("end_date cannot precede start_date")
        if (end - start).days > _MAX_HORIZON_DAYS:
            raise ForecastError("forecast horizon cannot exceed 10 years")
        normalized_granularity = self._granularity(granularity)
        base_currency = self._fx.base_currency(book_id)
        occurrences = self._scheduled.project_occurrences(
            book_id=book_id,
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            max_occurrences=_MAX_OCCURRENCES,
        )

        buckets: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "inflow": 0,
                "outflow": 0,
                "complete": True,
                "missing": set(),
                "occurrenceCount": 0,
                "transferCount": 0,
            }
        )
        details: list[dict[str, object]] = []
        overall_missing: set[tuple[str, str]] = set()
        total_inflow = 0
        total_outflow = 0
        total_complete = True
        transfer_count = 0

        for occurrence in occurrences:
            due_date = str(occurrence["dueDate"])
            kind = str(occurrence["kind"])
            bucket_key = self._bucket(due_date, normalized_granularity)
            bucket = buckets[bucket_key]
            bucket["occurrenceCount"] = int(bucket["occurrenceCount"]) + 1
            direction = self._direction(kind)
            converted: int | None = None
            missing: tuple[str, str] | None = None

            if direction == "TRANSFER":
                bucket["transferCount"] = int(bucket["transferCount"]) + 1
                transfer_count += 1
            else:
                try:
                    converted = self._fx.convert_minor(
                        book_id=book_id,
                        amount_minor=int(occurrence["amountMinor"]),
                        currency_code=str(occurrence["currency"]),
                        rate_date=due_date,
                    )
                except FxRateMissingError as exc:
                    missing = (exc.currency_code, exc.rate_date)
                    bucket["complete"] = False
                    bucket["missing"].add(missing)
                    overall_missing.add(missing)
                    total_complete = False
                else:
                    if direction == "INFLOW":
                        bucket["inflow"] = int(bucket["inflow"]) + converted
                        total_inflow += converted
                    else:
                        bucket["outflow"] = int(bucket["outflow"]) + converted
                        total_outflow += converted

            details.append(
                {
                    **occurrence,
                    "direction": direction,
                    "baseAmountMinor": converted,
                    "complete": missing is None,
                    "missingFx": []
                    if missing is None
                    else self._missing_payload({missing}),
                }
            )

        bucket_payload: list[dict[str, object]] = []
        for label in sorted(buckets):
            bucket = buckets[label]
            complete = bool(bucket["complete"])
            inflow = int(bucket["inflow"])
            outflow = int(bucket["outflow"])
            bucket_payload.append(
                {
                    "period": label,
                    "inflowMinor": inflow if complete else None,
                    "outflowMinor": outflow if complete else None,
                    "netMinor": inflow - outflow if complete else None,
                    "complete": complete,
                    "occurrenceCount": int(bucket["occurrenceCount"]),
                    "transferCount": int(bucket["transferCount"]),
                    "missingFx": self._missing_payload(bucket["missing"]),
                }
            )

        return {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "granularity": normalized_granularity,
            "baseCurrency": base_currency,
            "fxPolicy": "LATEST_KNOWN_ON_OR_BEFORE_DUE_DATE",
            "scheduledOnly": True,
            "complete": total_complete,
            "totalInflowMinor": total_inflow if total_complete else None,
            "totalOutflowMinor": total_outflow if total_complete else None,
            "totalNetMinor": (
                total_inflow - total_outflow if total_complete else None
            ),
            "occurrenceCount": len(details),
            "transferCount": transfer_count,
            "missingFx": self._missing_payload(overall_missing),
            "buckets": bucket_payload,
            "occurrences": details,
        }

    @staticmethod
    def _direction(kind: str) -> str:
        if kind == "EXPENSE":
            return "OUTFLOW"
        if kind in {"INCOME", "REFUND"}:
            return "INFLOW"
        if kind == "TRANSFER":
            return "TRANSFER"
        raise ForecastError(f"unsupported scheduled kind: {kind}")

    @staticmethod
    def _bucket(due_date: str, granularity: str) -> str:
        if granularity == "DAY":
            return due_date
        if granularity == "MONTH":
            return due_date[:7]
        return due_date[:4]

    @staticmethod
    def _granularity(value: str) -> str:
        if not isinstance(value, str):
            raise ForecastError("granularity must be DAY, MONTH or YEAR")
        normalized = value.strip().upper()
        if normalized not in _GRANULARITIES:
            raise ForecastError("granularity must be DAY, MONTH or YEAR")
        return normalized

    @staticmethod
    def _parse_date(value: str, field: str) -> date:
        if not isinstance(value, str):
            raise ForecastError(f"invalid {field}")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ForecastError(f"invalid {field}") from exc

    @staticmethod
    def _missing_payload(
        items: set[tuple[str, str]],
    ) -> list[dict[str, str]]:
        return [
            {"currency": currency, "date": rate_date}
            for currency, rate_date in sorted(items)
        ]
