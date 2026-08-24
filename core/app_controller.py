from __future__ import annotations

from config.constants import SCHEMA_VERSION
from config.settings import Settings
from core.account_service import AccountService
from core.app_state_service import AppStateService
from core.book_service import BookService
from core.database import Database
from core.errors import FinanceTrackerError, ValidationError
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.money import parse_money
from core.payee_service import PayeeService
from core.reconciliation_service import ReconciliationService
from core.reporting_service import ReportingService
from core.scheduled_transaction_service import ScheduledTransactionService
from core.transport import TransportSerializer


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
        reconciliation_service: ReconciliationService | None = None,
        scheduled_service: ScheduledTransactionService | None = None,
        app_state_service: AppStateService | None = None,
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
        self._reconciliation = reconciliation_service or ReconciliationService(
            database, account_service, ledger_service, payee_service
        )
        self._scheduled = scheduled_service or ScheduledTransactionService(
            database, account_service, ledger_service, payee_service
        )
        self._app_state = app_state_service or AppStateService(database, account_service)

    def initial_state(self) -> dict[str, object]:
        book = self._books.current_book()
        return {
            "app": "Finance Tracker",
            "schemaVersion": SCHEMA_VERSION,
            "bookCurrency": self._settings.book_currency,
            "locale": self._settings.locale,
            "reconciliationReviewMode": self._settings.reconciliation_review_mode,
            "currencies": self._app_state.supported_currencies(),
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
        return TransportSerializer.serialize(
            self._app_state.snapshot(
                book_id=book.id,
                book_name=book.name,
                book_currency=book.base_currency_code,
            )
        )

    def dashboard(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        result = self._reporting.dashboard(
            book_id=book.id,
            start_date=str(payload.get("startDate", "")),
            end_date=str(payload.get("endDate", "")),
            as_of_date=str(payload.get("asOfDate", "")),
        )
        return TransportSerializer.serialize(result)

    def account_history(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        result = self._reporting.account_history(
            book_id=book.id,
            account_id=self._positive_id(payload.get("accountId")),
            start_date=str(payload.get("startDate", "")),
            end_date=str(payload.get("endDate", "")),
        )
        return TransportSerializer.serialize(result)

    def set_fx_rate(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        rate = self._fx.set_rate(
            book_id=book.id,
            currency_code=str(payload.get("currency", "")),
            rate_date=str(payload.get("date", "")),
            rate=payload.get("rate", ""),
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

    def import_csv(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return self._reconciliation.import_csv(
            book_id=book.id,
            account_id=self._positive_id(payload.get("accountId")),
            source_name=str(payload.get("sourceName", "")),
            csv_text=str(payload.get("csvText", "")),
            review_mode=str(
                payload.get("reviewMode", self._settings.reconciliation_review_mode)
            ),
        )

    def list_import_batches(self) -> list[dict[str, object]]:
        book = self._require_book()
        return self._reconciliation.list_batches(book.id)

    def import_batch_rows(self, payload: dict[str, object]) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._reconciliation.batch_rows(
                book.id, self._positive_id(payload.get("batchId"))
            )
        )

    def link_import_row(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return self._reconciliation.link_existing(
            book_id=book.id,
            row_id=self._positive_id(payload.get("rowId")),
            transaction_id=self._positive_id(payload.get("transactionId")),
        )

    def post_import_row(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        payee = payload.get("payeeId")
        result = self._reconciliation.post_row(
            book_id=book.id,
            row_id=self._positive_id(payload.get("rowId")),
            posting_kind=str(payload.get("postingKind", "")),
            counter_account_id=self._positive_id(payload.get("counterAccountId")),
            payee_id=None if payee in (None, "") else self._positive_id(payee),
        )
        return {**result, "stateSnapshot": self.snapshot()}

    def ignore_import_row(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return self._reconciliation.ignore_row(
            book_id=book.id,
            row_id=self._positive_id(payload.get("rowId")),
        )

    def create_scheduled_transaction(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        book = self._require_book()
        source_id = self._positive_id(payload.get("sourceAccountId"))
        source = self._accounts.get_account(book.id, source_id)
        if source.currency_code is None:
            raise ValidationError("scheduled source must be a balance account")
        amount = parse_money(
            payload.get("amount", ""), self._database.currency(source.currency_code)
        )
        payee = payload.get("payeeId")
        try:
            interval = int(payload.get("interval", 1))
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid schedule interval") from exc
        item = self._scheduled.create_schedule(
            book_id=book.id,
            kind=str(payload.get("kind", "")),
            source_account_id=source_id,
            counter_account_id=self._positive_id(payload.get("counterAccountId")),
            amount_minor=amount,
            frequency=str(payload.get("frequency", "")),
            interval=interval,
            start_date=str(payload.get("startDate", "")),
            end_date=None
            if payload.get("endDate") in (None, "")
            else str(payload.get("endDate")),
            description=str(payload.get("description", "")),
            payee_id=None if payee in (None, "") else self._positive_id(payee),
        )
        return TransportSerializer.serialize(self._scheduled_payload(item))

    def list_scheduled_transactions(self) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(
            [self._scheduled_payload(item) for item in self._scheduled.list_schedules(book.id)]
        )

    def set_scheduled_active(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        active = payload.get("active")
        if not isinstance(active, bool):
            raise ValidationError("active must be boolean")
        item = self._scheduled.set_active(
            book.id,
            self._positive_id(payload.get("scheduleId")),
            active,
        )
        return TransportSerializer.serialize(self._scheduled_payload(item))

    def post_due_scheduled(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        schedule_id = payload.get("scheduleId")
        try:
            max_occurrences = int(payload.get("maxOccurrences", 1000))
        except (TypeError, ValueError) as exc:
            raise ValidationError("invalid occurrence limit") from exc
        posted = self._scheduled.post_due(
            book_id=book.id,
            as_of_date=str(payload.get("asOfDate", "")),
            schedule_id=None
            if schedule_id in (None, "")
            else self._positive_id(schedule_id),
            max_occurrences=max_occurrences,
        )
        return {
            "posted": posted,
            "count": len(posted),
            "state": self.snapshot(),
        }

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
        if source.type not in {"ASSET", "LIABILITY"} or source.currency_code is None:
            raise ValidationError("source must be a balance account")
        amount = parse_money(
            payload.get("amount", ""), self._database.currency(source.currency_code)
        )
        if amount <= 0:
            raise ValidationError("expense amount must be positive")
        with self._database.transaction() as conn:
            transaction = self._ledger.create_expense(
                book_id=book.id,
                source_account_id=source_id,
                expense_account_id=category_id,
                amount_minor=amount,
                currency_code=source.currency_code,
                transaction_date=str(payload.get("date", "")),
                transaction_time=str(payload["time"]) if payload.get("time") else None,
                description=str(payload.get("description", "")).strip(),
                connection=conn,
            )
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

    def _scheduled_payload(self, item) -> dict[str, object]:
        source = self._accounts.get_account(item.book_id, item.source_account_id)
        counter = self._accounts.get_account(item.book_id, item.counter_account_id)
        return {
            "id": item.id,
            "kind": item.kind,
            "sourceAccountId": item.source_account_id,
            "sourceAccountName": source.name,
            "counterAccountId": item.counter_account_id,
            "counterAccountName": counter.name,
            "amountMinor": item.amount_minor,
            "currency": item.currency_code,
            "frequency": item.frequency,
            "interval": item.interval,
            "startDate": item.start_date,
            "nextDueDate": item.next_due_date,
            "endDate": item.end_date,
            "description": item.description,
            "payeeId": item.payee_id,
            "active": item.active,
        }

    def _require_book(self):
        book = self._books.current_book()
        if book is None:
            raise ValidationError("initial setup is required")
        return book

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
