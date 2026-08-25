from __future__ import annotations

from collections import defaultdict
from datetime import date

from core.errors import ForecastError, FxRateMissingError
from core.fx_service import FxService
from core.loan_service import LoanService
from core.posting_policy import PostingPolicy
from core.scheduled_transaction_service import ScheduledTransactionService

_GRANULARITIES = {"DAY", "MONTH", "YEAR"}
_MAX_HORIZON_DAYS = 3660
_MAX_OCCURRENCES = 10_000


class ForecastService:
    """Build deterministic read-only forecasts from canonical future obligations."""

    def __init__(
        self,
        scheduled: ScheduledTransactionService,
        fx: FxService,
        loans: LoanService | None = None,
    ) -> None:
        self._scheduled = scheduled
        self._fx = fx
        self._loans = loans

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
        scheduled = [
            {**item, "source": "SCHEDULED_TRANSACTION"}
            for item in self._scheduled.project_occurrences(
                book_id=book_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                max_occurrences=_MAX_OCCURRENCES,
            )
        ]
        loan_occurrences = (
            []
            if self._loans is None
            else self._loans.project_payments(
                book_id=book_id,
                start_date=start.isoformat(),
                end_date=end.isoformat(),
            )
        )
        occurrences = scheduled + loan_occurrences
        if len(occurrences) > _MAX_OCCURRENCES:
            raise ForecastError("forecast occurrence limit reached")
        occurrences.sort(
            key=lambda item: (
                str(item["dueDate"]),
                str(item["source"]),
                int(item.get("scheduleId", item.get("loanId", 0))),
            )
        )

        buckets: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "inflow": 0,
                "outflow": 0,
                "complete": True,
                "missing": set(),
                "occurrenceCount": 0,
                "transferCount": 0,
                "loanInstallmentCount": 0,
            }
        )
        details: list[dict[str, object]] = []
        overall_missing: set[tuple[str, str]] = set()
        total_inflow = 0
        total_outflow = 0
        total_complete = True
        transfer_count = 0
        loan_installment_count = 0

        for occurrence in occurrences:
            due_date = str(occurrence["dueDate"])
            source = str(occurrence["source"])
            bucket_key = self._bucket(due_date, normalized_granularity)
            bucket = buckets[bucket_key]
            bucket["occurrenceCount"] = int(bucket["occurrenceCount"]) + 1
            if source == "LOAN_INSTALLMENT":
                direction = "OUTFLOW"
                kind = "LOAN_PAYMENT"
                flow_amount_minor = int(occurrence["interestMinor"])
                bucket["loanInstallmentCount"] = int(bucket["loanInstallmentCount"]) + 1
                loan_installment_count += 1
            else:
                kind = str(occurrence["kind"])
                flow_amount_minor = int(occurrence["amountMinor"])
                try:
                    direction = PostingPolicy.book_cash_flow_direction(kind)
                except ValueError as exc:
                    raise ForecastError(f"unsupported scheduled kind: {kind}") from exc

            converted: int | None = None
            flow_converted: int | None = None
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
                    flow_converted = (
                        converted
                        if flow_amount_minor == int(occurrence["amountMinor"])
                        else self._fx.convert_minor(
                            book_id=book_id,
                            amount_minor=flow_amount_minor,
                            currency_code=str(occurrence["currency"]),
                            rate_date=due_date,
                        )
                    )
                except FxRateMissingError as exc:
                    missing = (exc.currency_code, exc.rate_date)
                    bucket["complete"] = False
                    bucket["missing"].add(missing)
                    overall_missing.add(missing)
                    total_complete = False
                else:
                    if direction == "INFLOW":
                        bucket["inflow"] = int(bucket["inflow"]) + int(flow_converted)
                        total_inflow += int(flow_converted)
                    else:
                        bucket["outflow"] = int(bucket["outflow"]) + int(flow_converted)
                        total_outflow += int(flow_converted)

            details.append(
                {
                    **occurrence,
                    "kind": kind,
                    "direction": direction,
                    "baseAmountMinor": converted,
                    "flowBaseAmountMinor": flow_converted,
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
                    "loanInstallmentCount": int(bucket["loanInstallmentCount"]),
                    "missingFx": self._missing_payload(bucket["missing"]),
                }
            )

        sources = ["SCHEDULED_TRANSACTIONS"]
        if self._loans is not None:
            sources.append("LOAN_INSTALLMENTS")
        return {
            "startDate": start.isoformat(),
            "endDate": end.isoformat(),
            "granularity": normalized_granularity,
            "baseCurrency": base_currency,
            "fxPolicy": "LATEST_KNOWN_ON_OR_BEFORE_DUE_DATE",
            "sources": sources,
            "scheduledOnly": self._loans is None,
            "complete": total_complete,
            "totalInflowMinor": total_inflow if total_complete else None,
            "totalOutflowMinor": total_outflow if total_complete else None,
            "totalNetMinor": (
                total_inflow - total_outflow if total_complete else None
            ),
            "occurrenceCount": len(details),
            "transferCount": transfer_count,
            "loanInstallmentCount": loan_installment_count,
            "missingFx": self._missing_payload(overall_missing),
            "buckets": bucket_payload,
            "occurrences": details,
        }

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
