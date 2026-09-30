from __future__ import annotations

_FINANCIAL_INTEGER_FIELDS = {
    "amountMinor",
    "assetsMinor",
    "annualRateBps",
    "balanceMinor",
    "baseAmountMinor",
    "baseValueMinor",
    "currentAnnualRateBps",
    "expenseMinor",
    "endingBalanceMinor",
    "endingBaseValueMinor",
    "fixedPaymentMinor",
    "flowBaseAmountMinor",
    "incomeMinor",
    "inflowMinor",
    "interestMinor",
    "liabilitiesMinor",
    "nativeBalanceMinor",
    "netMinor",
    "netWorthMinor",
    "nextPaymentMinor",
    "originalPrincipalMinor",
    "outflowMinor",
    "openingBalanceMinor",
    "outstandingPrincipalMinor",
    "paymentMinor",
    "principalMinor",
    "quantityMinor",
    "remainingMinor",
    "remainingPrincipalMinor",
    "savingRateBps",
    "savingMinor",
    "spentMinor",
    "totalBudgetMinor",
    "totalInflowMinor",
    "totalInterestMinor",
    "totalNetMinor",
    "totalOutflowMinor",
    "totalPaidMinor",
    "totalRemainingMinor",
    "totalSpentMinor",
    "usageBps",
    "valueMinor",
    "amount_minor",
    "base_value_minor",
    "balance_minor",
    "expense_minor",
    "income_minor",
    "net_minor",
    "quantity_minor",
    "value_minor",
}


class TransportSerializer:
    """Serialize values crossing QWebChannel without JS integer precision loss.

    Financial integer fields are explicit protocol vocabulary. Adding a new
    monetary or basis-point field requires adding it here and exercising it in
    tests, instead of relying on an implicit suffix convention.
    """

    @classmethod
    def serialize(cls, value: object, key: str | None = None):
        if value is None:
            return None
        if key in _FINANCIAL_INTEGER_FIELDS and isinstance(value, int):
            return str(value)
        if isinstance(value, dict):
            return {
                item_key: cls.serialize(item, str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, list):
            return [cls.serialize(item) for item in value]
        if isinstance(value, tuple):
            return [cls.serialize(item) for item in value]
        return value

    @staticmethod
    def financial_integer_fields() -> frozenset[str]:
        return frozenset(_FINANCIAL_INTEGER_FIELDS)
