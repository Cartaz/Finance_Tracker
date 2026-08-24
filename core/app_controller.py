from __future__ import annotations

from config.constants import SCHEMA_VERSION
from config.settings import Settings
from core.account_service import AccountService
from core.book_service import BookService
from core.database import Database
from core.errors import FinanceTrackerError, ValidationError
from core.fx_service import FxService
from core.ledger_service import EntryDraft, LedgerService, TransactionDraft
from core.money import parse_money
from core.payee_service import PayeeService
from core.reporting_service import ReportingService


class AppController:
    """Thin coordinator used by the QWebChannel bridge."""

    def __init__(
        self,
        database: Database,
        settings: Settings,
        account_service: AccountService,
        ledger_service: LedgerService,
        book_service: BookService,
        payee_service: PayeeService,
        fx_service: FxService | None = None,
        reporting_service: ReportingService | None = None,
    ) -> None:
        self._database = database
        self._settings = settings
        self._accounts = account_service
        self._ledger = ledger_service
        self._books = book_service
        self._payees = payee_service
        self._fx = fx_service or FxService(database)
        self._reporting = reporting_service or ReportingService(
            database, self._fx, account_service
        )

    def initial_state(self) -> dict[str, object]:
        book = self._books.current_book()
        return {
            "app": "Finance Tracker",
            "schemaVersion": SCHEMA_VERSION,
            "bookCurrency": self._settings.book_currency,
            "locale": self._settings.locale,
            "currencies": self._supported_currencies(),
            "needsSetup": book is None,
            "book": None
            if book is None
            else {"id": book.id, "name": book.name, "currency": book.base_currency_code},
        }

    def setup(self, payload: dict[str, object]) -> dict[str, object]:
        self._books.create_personal_book(
            user_name=str(payload.get("userName", "")),
            book_name=str(payload.get("bookName", "")),
            currency_code=str(payload.get("currency", self._settings.book_currency)),
        )
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        book = self._require_book()
        accounts = self._accounts.list_accounts(book.id)
        transactions = self._database.connection.execute(
            """
            SELECT t.id, t.kind, t.transaction_date, t.transaction_time, t.currency_code,
                   t.description, p.name AS payee_name
            FROM transactions t LEFT JOIN payees p ON p.id = t.payee_id
            WHERE t.book_id = ?
            ORDER BY t.transaction_date DESC, COALESCE(t.transaction_time, '') DESC, t.id DESC
            LIMIT 100
            """,
            (book.id,),
        ).fetchall()
        return self._transport_money(
            {
                "book": {
                    "id": book.id,
                    "name": book.name,
                    "currency": book.base_currency_code,
                },
                "accounts": [
                    {
                        "id": item.id,
                        "name": item.name,
                        "type": item.type,
                        "currency": item.currency_code,
                        "placeholder": item.placeholder,
                        "balanceMinor": self._accounts.native_balance(book.id, item.id)
                        if item.type in {"ASSET", "LIABILITY"}
                        else None,
                    }
                    for item in accounts
                ],
                "transactions": [dict(row) for row in transactions],
            }
        )

    def dashboard(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        result = self._reporting.dashboard(
            book_id=book.id,
            start_date=str(payload.get("startDate", "")),
            end_date=str(payload.get("endDate", "")),
            as_of_date=str(payload.get("asOfDate", "")),
        )
        return self._transport_money(result)

    def account_history(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        result = self._reporting.account_history(
            book_id=book.id,
            account_id=self._positive_id(payload.get("accountId")),
            start_date=str(payload.get("startDate", "")),
            end_date=str(payload.get("endDate", "")),
        )
        return self._transport_money(result)

    def set_fx_rate(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        rate = self._fx.set_rate(
            book_id=book.id,
            currency_code=str(payload.get("currency", "")),
            rate_date=str(payload.get("date", "")),
            rate=str(payload.get("rate", "")),
        )
        return {
            "currency": rate.currency_code,
            "date": rate.rate_date,
            "rate": format(rate.rate, "f"),
        }

    def list_fx_rates(self) -> list[dict[str, object]]:
        book = self._require_book()
        return [
            {
                "currency": item.currency_code,
                "date": item.rate_date,
                "rate": format(item.rate, "f"),
            }
            for item in self._fx.list_rates(book.id)
        ]

    def create_account(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        account_type = str(payload.get("type", "")).upper()
        currency = (
            str(payload.get("currency", book.base_currency_code))
            if account_type in {"ASSET", "LIABILITY"}
            else None
        )
        account = self._accounts.create_account(
            book_id=book.id,
            account_type=account_type,
            name=str(payload.get("name", "")),
            currency_code=currency,
            tracking_start_date=str(payload.get("trackingStartDate", ""))
            if currency
            else None,
            tracking_start_time=str(payload["trackingStartTime"])
            if payload.get("trackingStartTime")
            else None,
            placeholder=bool(payload.get("placeholder", False)),
        )
        return {"id": account.id, "state": self.snapshot()}

    def create_expense(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        source_id = self._positive_id(payload.get("sourceAccountId"))
        category_id = self._positive_id(payload.get("categoryAccountId"))
        source = self._accounts.get_account(book.id, source_id)
        category = self._accounts.get_account(book.id, category_id)
        if source.type not in {"ASSET", "LIABILITY"} or source.currency_code is None:
            raise ValidationError("source must be a balance account")
        if category.type != "EXPENSE" or category.placeholder or category.archived:
            raise ValidationError("category must be an active selectable expense account")
        amount = parse_money(
            str(payload.get("amount", "")), self._database.currency(source.currency_code)
        )
        if amount <= 0:
            raise ValidationError("expense amount must be positive")
        draft = TransactionDraft(
            book_id=book.id,
            kind="EXPENSE",
            transaction_date=str(payload.get("date", "")),
            transaction_time=str(payload["time"]) if payload.get("time") else None,
            currency_code=source.currency_code,
            description=str(payload.get("description", "")).strip(),
            entries=(
                EntryDraft(source_id, -amount, -amount),
                EntryDraft(category_id, amount, None),
            ),
        )
        with self._database.transaction() as conn:
            transaction = self._ledger.create_transaction(draft, connection=conn)
            payee_id = payload.get("payeeId")
            if payee_id is not None:
                self._payees.assign_transaction(
                    book_id=book.id,
                    transaction_id=transaction.id,
                    payee_id=self._positive_id(payee_id),
                    connection=conn,
                )
        return {"id": transaction.id, "state": self.snapshot()}

    def suggest_payees(self, query: str) -> list[dict[str, object]]:
        book = self._require_book()
        return [
            {
                "id": item.id,
                "name": item.name,
                "usageCount": item.usage_count,
                "matchedBy": item.matched_by,
            }
            for item in self._payees.suggest_payees(book.id, query, limit=5)
        ]

    def create_payee(self, name: str) -> dict[str, object]:
        book = self._require_book()
        item = self._payees.create_payee(book_id=book.id, name=name)
        return {"id": item.id, "name": item.name}

    def _require_book(self):
        book = self._books.current_book()
        if book is None:
            raise ValidationError("initial setup is required")
        return book

    def _supported_currencies(self) -> list[dict[str, object]]:
        rows = self._database.connection.execute(
            """
            SELECT code, minor_unit_digits
            FROM currencies
            WHERE active = 1
            ORDER BY code
            """
        ).fetchall()
        return [
            {
                "code": str(row["code"]),
                "minorUnitDigits": int(row["minor_unit_digits"]),
            }
            for row in rows
        ]

    @classmethod
    def _transport_money(cls, value, key: str | None = None):
        if value is None:
            return None
        if (
            key is not None
            and key.endswith(("Minor", "Bps"))
            and isinstance(value, int)
        ):
            return str(value)
        if isinstance(value, dict):
            return {
                item_key: cls._transport_money(item, item_key)
                for item_key, item in value.items()
            }
        if isinstance(value, list):
            return [cls._transport_money(item) for item in value]
        return value

    @staticmethod
    def _positive_id(value: object) -> int:
        if isinstance(value, bool):
            raise ValidationError("invalid identifier")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid identifier") from exc
        if parsed < 1:
            raise ValidationError("invalid identifier")
        return parsed

    @staticmethod
    def error_payload(exc: Exception) -> dict[str, object]:
        if isinstance(exc, FinanceTrackerError):
            return {
                "ok": False,
                "error": {"code": type(exc).__name__, "message": str(exc)},
            }
        raise exc
