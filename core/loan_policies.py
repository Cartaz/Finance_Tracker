from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext

from core.errors import LoanError

AMORTIZATION_TYPES = frozenset({"FRENCH", "ITALIAN", "BULLET"})
RATE_TYPES = frozenset({"FIXED", "VARIABLE"})
RECAST_STRATEGIES = frozenset({"REDUCE_PAYMENT", "REDUCE_TERM"})


@dataclass(frozen=True, slots=True)
class InstallmentTerms:
    principal_minor: int
    interest_minor: int
    payment_minor: int


class AmortizationPolicy:
    """Pure deterministic amortization math.

    The policy receives canonical principal/rate inputs and never reads or writes
    persistence. All monetary values are integer minor units and all division or
    percentage math uses Decimal.
    """

    @classmethod
    def installment(
        cls,
        *,
        amortization_type: str,
        outstanding_minor: int,
        annual_rate_bps: int,
        remaining_installments: int,
        original_principal_minor: int,
        original_term_months: int,
        installment_number: int,
        recast_strategy: str,
        fixed_french_payment_minor: int | None = None,
    ) -> InstallmentTerms:
        amortization = cls.normalize_amortization(amortization_type)
        strategy = cls.normalize_recast_strategy(recast_strategy)
        if outstanding_minor <= 0:
            raise LoanError("outstanding principal must be positive")
        if remaining_installments <= 0:
            raise LoanError("loan has no remaining contractual installments")
        if not 0 <= annual_rate_bps <= 100_000:
            raise LoanError("annual rate is outside supported range")

        interest = cls.interest_minor(outstanding_minor, annual_rate_bps)
        is_last = remaining_installments == 1

        if amortization == "BULLET":
            principal = outstanding_minor if is_last else 0
            return InstallmentTerms(principal, interest, principal + interest)

        if amortization == "ITALIAN":
            if strategy == "REDUCE_PAYMENT":
                principal = cls.round_minor(
                    Decimal(outstanding_minor) / Decimal(remaining_installments)
                )
            else:
                principal = cls.round_minor(
                    Decimal(original_principal_minor) / Decimal(original_term_months)
                )
            principal = outstanding_minor if is_last else min(outstanding_minor, max(1, principal))
            return InstallmentTerms(principal, interest, principal + interest)

        if fixed_french_payment_minor is None:
            payment = cls.french_payment_minor(
                outstanding_minor,
                annual_rate_bps,
                remaining_installments,
            )
        else:
            payment = fixed_french_payment_minor
        principal = payment - interest
        if principal <= 0:
            raise LoanError("contract payment does not amortize principal")
        principal = outstanding_minor if is_last else min(outstanding_minor, principal)
        return InstallmentTerms(principal, interest, principal + interest)

    @staticmethod
    def french_payment_minor(
        principal_minor: int,
        annual_rate_bps: int,
        term_months: int,
    ) -> int:
        if principal_minor <= 0 or term_months <= 0:
            raise LoanError("invalid French amortization inputs")
        if annual_rate_bps == 0:
            return max(
                1,
                AmortizationPolicy.round_minor(
                    Decimal(principal_minor) / Decimal(term_months)
                ),
            )
        with localcontext() as context:
            context.prec = 50
            monthly_rate = Decimal(annual_rate_bps) / Decimal(10_000) / Decimal(12)
            factor = (Decimal(1) + monthly_rate) ** (-term_months)
            payment = Decimal(principal_minor) * monthly_rate / (Decimal(1) - factor)
            return max(1, AmortizationPolicy.round_minor(payment))

    @staticmethod
    def interest_minor(balance_minor: int, annual_rate_bps: int) -> int:
        if annual_rate_bps == 0:
            return 0
        with localcontext() as context:
            context.prec = 50
            value = (
                Decimal(balance_minor)
                * Decimal(annual_rate_bps)
                / Decimal(10_000)
                / Decimal(12)
            )
            return AmortizationPolicy.round_minor(value)

    @staticmethod
    def round_minor(value: Decimal) -> int:
        return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    @staticmethod
    def normalize_amortization(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if normalized not in AMORTIZATION_TYPES:
            raise LoanError("amortization_type must be FRENCH, ITALIAN or BULLET")
        return normalized

    @staticmethod
    def normalize_rate_type(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if normalized not in RATE_TYPES:
            raise LoanError("rate_type must be FIXED or VARIABLE")
        return normalized

    @staticmethod
    def normalize_recast_strategy(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if normalized not in RECAST_STRATEGIES:
            raise LoanError("recast_strategy must be REDUCE_PAYMENT or REDUCE_TERM")
        return normalized
