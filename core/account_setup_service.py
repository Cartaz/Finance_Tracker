from __future__ import annotations

from core.account_service import Account, AccountService
from core.category_service import CategoryService
from core.database import Database
from core.errors import ValidationError
from core.ledger_service import LedgerService

_BALANCE_TYPES = {"ASSET", "LIABILITY"}
_CATEGORY_TYPES = {"EXPENSE", "INCOME"}
_OPENING_DIRECTIONS = {"POSITIVE", "NEGATIVE"}


class AccountSetupService:
    """Own user-facing account/category creation workflows.

    Balance-account creation may include an opening balance. The balance account,
    its hidden technical equity counter-account, and the opening-balance ledger
    transaction are committed atomically.
    """

    def __init__(
        self,
        database: Database,
        accounts: AccountService,
        categories: CategoryService,
        ledger: LedgerService,
    ) -> None:
        self._database = database
        self._accounts = accounts
        self._categories = categories
        self._ledger = ledger

    def create_balance_account(
        self,
        *,
        book_id: int,
        account_type: str,
        name: str,
        currency_code: str,
        tracking_start_date: str,
        tracking_start_time: str | None = None,
        placeholder: bool = False,
        opening_balance_minor: int | None = None,
        opening_balance_direction: str | None = None,
    ) -> Account:
        account_type = account_type.upper()
        if account_type not in _BALANCE_TYPES:
            raise ValidationError("balance account type must be ASSET or LIABILITY")
        if opening_balance_minor is not None:
            if placeholder:
                raise ValidationError("a placeholder account cannot have an opening balance")
            if isinstance(opening_balance_minor, bool) or opening_balance_minor <= 0:
                raise ValidationError("opening balance must be a positive minor-unit magnitude")
            direction = (
                opening_balance_direction
                or ("POSITIVE" if account_type == "ASSET" else "NEGATIVE")
            ).upper()
            if direction not in _OPENING_DIRECTIONS:
                raise ValidationError("opening balance direction must be POSITIVE or NEGATIVE")
        else:
            direction = None

        with self._database.transaction() as conn:
            account = self._accounts.create_account(
                book_id=book_id,
                account_type=account_type,
                name=name,
                currency_code=currency_code,
                tracking_start_date=tracking_start_date,
                tracking_start_time=tracking_start_time,
                placeholder=placeholder,
                connection=conn,
            )
            if opening_balance_minor is None:
                return account

            technical_equity = self._accounts.create_account(
                book_id=book_id,
                account_type="EQUITY",
                name=f"Saldo iniziale · {account.name}",
                connection=conn,
            )
            signed_quantity = (
                opening_balance_minor if direction == "POSITIVE" else -opening_balance_minor
            )
            self._ledger.create_opening_balance(
                book_id=book_id,
                account_id=account.id,
                equity_account_id=technical_equity.id,
                quantity_minor=signed_quantity,
                currency_code=currency_code,
                transaction_date=tracking_start_date,
                transaction_time=tracking_start_time,
                description=f"Saldo iniziale · {account.name}",
                connection=conn,
            )
            return account

    def create_category(
        self,
        *,
        book_id: int,
        category_type: str,
        name: str,
        parent_id: int | None = None,
        placeholder: bool = False,
    ) -> Account:
        category_type = category_type.upper()
        if category_type not in _CATEGORY_TYPES:
            raise ValidationError("category type must be EXPENSE or INCOME")
        return self._categories.create_category(
            book_id=book_id,
            category_type=category_type,
            name=name,
            parent_id=parent_id,
            placeholder=placeholder,
        )
