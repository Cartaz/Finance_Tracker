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
