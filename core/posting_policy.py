from __future__ import annotations

_BALANCE_TYPES = {"ASSET", "LIABILITY"}
_POSTING_KINDS = {"EXPENSE", "INCOME", "REFUND", "TRANSFER"}


class PostingPolicy:
    """Canonical capability and high-level semantics shared by workflows.

    LedgerService remains authoritative for actual posting validity. This policy
    answers which high-level posting choices are meaningful before a ledger
    mutation is attempted and exposes semantics that must not be re-derived by
    consumers such as forecasting or presentation DTOs.
    """

    @staticmethod
    def normalize_kind(value: str) -> str:
        normalized = value.strip().upper() if isinstance(value, str) else ""
        if normalized not in _POSTING_KINDS:
            raise ValueError("unsupported posting kind")
        return normalized

    @staticmethod
    def book_cash_flow_direction(kind: str) -> str:
        """Return the book-level cash-flow direction for a posting kind."""
        normalized = PostingPolicy.normalize_kind(kind)
        if normalized == "EXPENSE":
            return "OUTFLOW"
        if normalized in {"INCOME", "REFUND"}:
            return "INFLOW"
        return "TRANSFER"

    @staticmethod
    def allowed_kinds_for_amount(amount_minor: int) -> tuple[str, ...]:
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if amount_minor < 0:
            return ("EXPENSE", "TRANSFER")
        if amount_minor > 0:
            return ("INCOME", "REFUND", "TRANSFER")
        return ()

    @staticmethod
    def counter_is_eligible(
        kind: str,
        *,
        source_account_id: int,
        source_currency: str,
        counter_account_id: int,
        counter_type: str,
        counter_currency: str | None,
        counter_archived: bool,
        counter_placeholder: bool,
    ) -> bool:
        try:
            normalized = PostingPolicy.normalize_kind(kind)
        except ValueError:
            return False
        if (
            counter_archived
            or counter_placeholder
            or counter_account_id == source_account_id
        ):
            return False
        if normalized in {"EXPENSE", "REFUND"}:
            return counter_type == "EXPENSE"
        if normalized == "INCOME":
            return counter_type == "INCOME"
        return counter_type in _BALANCE_TYPES and counter_currency == source_currency
