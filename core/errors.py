class FinanceTrackerError(Exception):
    """Base error for expected Finance Tracker failures."""


class ValidationError(FinanceTrackerError):
    """Base error for invalid domain input."""


class MoneyParseError(ValidationError):
    """Raised when a monetary string cannot be parsed unambiguously."""


class CurrencyPrecisionError(ValidationError):
    """Raised when an amount exceeds a currency's supported precision."""


class UnsupportedCurrencyError(ValidationError):
    """Raised when a requested currency does not exist in the registry."""


class DatabaseIntegrityError(FinanceTrackerError):
    """Raised when database configuration or integrity checks fail."""


class AccountError(ValidationError):
    """Base error for invalid account operations."""


class AccountNotFoundError(AccountError):
    """Raised when an account does not exist in the requested book."""


class AccountArchivedError(AccountError):
    """Raised when an archived account is used for a new posting."""


class AccountPlaceholderError(AccountError):
    """Raised when a placeholder account is used for a new posting."""


class AccountHierarchyError(AccountError):
    """Raised when an account hierarchy operation is invalid."""


class CrossBookReferenceError(ValidationError):
    """Raised when an entity from another book is referenced."""


class LedgerValidationError(ValidationError):
    """Base error for invalid ledger operations."""


class UnbalancedTransactionError(LedgerValidationError):
    """Raised when transaction entry values do not sum to zero."""


class TrackingBoundaryError(LedgerValidationError):
    """Raised when a posting precedes an account tracking boundary."""


class TrackingBoundaryAmbiguousError(LedgerValidationError):
    """Raised when temporal precision cannot resolve a tracking boundary."""


class PayeeError(ValidationError):
    """Base error for invalid payee operations."""


class PayeeNotFoundError(PayeeError):
    """Raised when a payee or alias does not exist."""


class PayeeArchivedError(PayeeError):
    """Raised when an archived payee is used by a mutable operation."""


class PayeeCollisionError(PayeeError):
    """Raised when canonical payee names or aliases collide."""


class CategoryError(ValidationError):
    """Raised when a category operation is invalid."""


class FxRateError(ValidationError):
    """Raised when an FX rate is invalid or unavailable."""


class FxRateMissingError(FxRateError):
    """Raised when reporting needs an FX rate that has not been recorded."""

    def __init__(self, currency_code: str, rate_date: str) -> None:
        self.currency_code = currency_code
        self.rate_date = rate_date
        super().__init__(f"missing FX rate for {currency_code} on or before {rate_date}")


class ReportingError(ValidationError):
    """Raised when reporting input is invalid."""


class ReconciliationError(ValidationError):
    """Raised when CSV import or reconciliation input is invalid."""


class ReconciliationAmbiguousError(ReconciliationError):
    """Raised when a reconciliation identity is not uniquely resolvable."""
