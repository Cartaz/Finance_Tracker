from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from config.constants import SCHEMA_VERSION
from config.settings import Settings
from core.account_service import AccountService
from core.account_setup_service import AccountSetupService
from core.app_state_service import AppStateService
from core.book_service import BookService
from core.budget_service import BudgetService
from core.category_service import CategoryService
from core.database import Database
from core.errors import FinanceTrackerError, ValidationError
from core.forecast_service import ForecastService
from core.fx_service import FxService
from core.ledger_service import LedgerService
from core.loan_service import LoanService
from core.money import parse_money_magnitude
from core.payee_service import PayeeService
from core.rates import parse_annual_rate_bps
from core.reconciliation_service import ReconciliationService
from core.reporting_service import ReportingService
from core.scheduled_transaction_service import ScheduledTransactionService
from core.transport import TransportSerializer


class AppController:
    """Thin coordinator used by the QML bridge."""

    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        accounts: AccountService,
        ledger: LedgerService,
        books: BookService,
        payees: PayeeService,
        categories: CategoryService,
        account_setup: AccountSetupService,
        fx: FxService,
        reporting: ReportingService,
        reconciliation: ReconciliationService,
        reconciliation_factory: Callable[[Database], ReconciliationService],
        scheduled: ScheduledTransactionService,
        app_state: AppStateService,
        budgets: BudgetService,
        loans: LoanService,
        forecast: ForecastService,
    ) -> None:
        """Services are wired once by core.composition.build_controller."""
        self._database = database
        self._settings = settings
        self._accounts = accounts
        self._ledger = ledger
        self._books = books
        self._payees = payees
        self._categories = categories
        self._account_setup = account_setup
        self._fx = fx
        self._reporting = reporting
        self._reconciliation = reconciliation
        self._reconciliation_factory = reconciliation_factory
        self._scheduled = scheduled
        self._app_state = app_state
        self._budgets = budgets
        self._loans = loans
        self._forecast = forecast

    def initial_state(self) -> dict[str, object]:
        book = self._books.current_book()
        return {
            "app": "Finance Tracker",
            "schemaVersion": SCHEMA_VERSION,
            "bookCurrency": self._settings.book_currency,
            "reconciliationReviewMode": self._settings.reconciliation_review_mode,
            "currencies": self._app_state.supported_currencies(),
            "needsSetup": book is None,
            "book": None
            if book is None
            else {
                "id": book.id,
                "name": book.name,
                "currency": book.base_currency_code,
            },
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

    def forecast(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._forecast.cash_flow_forecast(
                book_id=book.id,
                start_date=str(payload.get("startDate", "")),
                end_date=str(payload.get("endDate", "")),
                granularity=str(payload.get("granularity", "MONTH")),
            )
        )

    def loan_capabilities(self) -> dict[str, object]:
        book = self._require_book()
        return TransportSerializer.serialize(self._loans.creation_capabilities(book.id))

    def create_loan(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        liability_id = self._positive_id(payload.get("liabilityAccountId"))
        liability = self._accounts.get_account(book.id, liability_id)
        if liability.currency_code is None:
            raise ValidationError("loan liability must have a native currency")
        mode = str(payload.get("mode", "EXISTING_BALANCE")).strip().upper()
        principal_minor = None
        funding_account_id = None
        start_date = None
        if mode == "NEW_DISBURSEMENT":
            principal_minor = parse_money_magnitude(
                payload.get("principal", ""),
                self._database.currency(liability.currency_code),
            )
            funding_account_id = self._positive_id(payload.get("fundingAccountId"))
            start_date = str(payload.get("startDate", ""))
        loan = self._loans.create_loan(
            book_id=book.id,
            name=str(payload.get("name", "")),
            liability_account_id=liability_id,
            payment_account_id=self._positive_id(payload.get("paymentAccountId")),
            interest_expense_account_id=self._positive_id(
                payload.get("interestExpenseAccountId")
            ),
            annual_rate_bps=parse_annual_rate_bps(payload.get("annualRate", "")),
            term_months=self._integer(payload.get("termMonths"), "termMonths"),
            first_due_date=str(payload.get("firstDueDate", "")),
            mode=mode,
            principal_minor=principal_minor,
            funding_account_id=funding_account_id,
            start_date=start_date,
            rate_type=str(payload.get("rateType", "FIXED")),
            amortization_type=str(payload.get("amortizationType", "FRENCH")),
            recast_strategy=str(payload.get("recastStrategy", "REDUCE_PAYMENT")),
        )
        return TransportSerializer.serialize(self._loans.status(book.id, loan.id))

    def list_loans(self) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(self._loans.list_loans(book.id))

    def loan_plan(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._loans.amortization_plan(
                book.id,
                self._positive_id(payload.get("loanId")),
            )
        )

    def loan_payments(self, payload: dict[str, object]) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._loans.list_payments(
                book.id,
                self._positive_id(payload.get("loanId")),
            )
        )

    def loan_rate_revisions(
        self, payload: dict[str, object]
    ) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._loans.list_rate_revisions(
                book.id,
                self._positive_id(payload.get("loanId")),
            )
        )

    def set_loan_variable_rate(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._loans.set_variable_rate(
                book_id=book.id,
                loan_id=self._positive_id(payload.get("loanId")),
                effective_date=str(payload.get("effectiveDate", "")),
                annual_rate_bps=parse_annual_rate_bps(payload.get("annualRate", "")),
            )
        )

    def post_next_loan_payment(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        payment = self._loans.post_next_payment(
            book_id=book.id,
            loan_id=self._positive_id(payload.get("loanId")),
        )
        return {
            "payment": TransportSerializer.serialize(payment),
            "state": self.snapshot(),
        }

    def post_custom_loan_payment(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        loan_id = self._positive_id(payload.get("loanId"))
        loan = self._loans.get_loan(book.id, loan_id)
        amount = parse_money_magnitude(
            payload.get("amount", ""), self._database.currency(loan.currency_code)
        )
        payment = self._loans.post_custom_payment(
            book_id=book.id,
            loan_id=loan_id,
            amount_minor=amount,
            recast_strategy=(
                None
                if payload.get("recastStrategy") in (None, "")
                else str(payload.get("recastStrategy"))
            ),
        )
        return {
            "payment": TransportSerializer.serialize(payment),
            "state": self.snapshot(),
        }

    def account_history(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        result = self._reporting.account_history(
            book_id=book.id,
            account_id=self._positive_id(payload.get("accountId")),
            start_date=str(payload.get("startDate", "")),
            end_date=str(payload.get("endDate", "")),
        )
        return TransportSerializer.serialize(result)

    def set_budget(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        amount = parse_money_magnitude(
            payload.get("amount", ""), self._database.currency(book.base_currency_code)
        )
        item = self._budgets.set_budget(
            book_id=book.id,
            category_account_id=self._positive_id(payload.get("categoryAccountId")),
            period=str(payload.get("period", "")),
            amount_minor=amount,
        )
        return TransportSerializer.serialize(
            {
                "id": item.id,
                "categoryAccountId": item.category_account_id,
                "period": item.period,
                "amountMinor": item.amount_minor,
            }
        )

    def budget_status(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._budgets.period_status(
                book_id=book.id,
                period=str(payload.get("period", "")),
            )
        )

    def delete_budget(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        budget_id = self._positive_id(payload.get("budgetId"))
        self._budgets.delete_budget(book_id=book.id, budget_id=budget_id)
        return {"deletedBudgetId": budget_id}

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

    def csv_import_task(self, payload: dict[str, object]) -> Callable[[Path], object]:
        """Validate arguments now; the returned task owns its worker SQLite connection."""
        arguments = self._csv_arguments(payload)
        path = self._database.path
        # Release the UI read snapshot before maintenance hands work to a worker.
        # Domain mutations are committed by their canonical services already.
        self._database.connection.commit()

        def run(csv_path: Path):
            worker_database = Database(path)
            try:
                service = self._reconciliation_factory(worker_database)
                return service.import_csv_file(csv_path=csv_path, **arguments)
            finally:
                worker_database.close()

        return run

    def _csv_arguments(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        return {
            "book_id": book.id,
            "account_id": self._positive_id(payload.get("accountId")),
            "source_name": payload.get("sourceName", ""),
            "review_mode": payload.get(
                "reviewMode", self._settings.reconciliation_review_mode
            ),
        }

    def list_import_batches(self) -> list[dict[str, object]]:
        book = self._require_book()
        return self._reconciliation.list_batches(book.id)

    def import_batch_rows(self, payload: dict[str, object]) -> list[dict[str, object]]:
        book = self._require_book()
        return TransportSerializer.serialize(
            self._reconciliation.batch_rows(
                book.id,
                self._positive_id(payload.get("batchId")),
                offset=self._integer(payload.get("offset", 0), "offset"),
                limit=self._integer(payload.get("limit", 101), "limit"),
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
        amount = parse_money_magnitude(
            payload.get("amount", ""), self._database.currency(source.currency_code)
        )
        payee = payload.get("payeeId")
        interval = self._integer(payload.get("interval", 1), "schedule interval")
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
            [
                self._scheduled_payload(item)
                for item in self._scheduled.list_schedules(book.id)
            ]
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
        max_occurrences = self._integer(
            payload.get("maxOccurrences", 1000), "occurrence limit"
        )
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
        account_type = str(payload.get("type", "")).strip().upper()
        name = str(payload.get("name", ""))
        placeholder = payload.get("placeholder", False)
        if not isinstance(placeholder, bool):
            raise ValidationError("placeholder must be boolean")

        if account_type in {"EXPENSE", "INCOME"}:
            parent_value = payload.get("parentId")
            account = self._account_setup.create_category(
                book_id=book.id,
                category_type=account_type,
                name=name,
                parent_id=(
                    None
                    if parent_value in (None, "")
                    else self._positive_id(parent_value)
                ),
                placeholder=placeholder,
            )
        elif account_type in {"ASSET", "LIABILITY"}:
            currency = str(payload.get("currency", book.base_currency_code))
            opening_text = str(payload.get("openingBalance", "")).strip()
            opening_minor = (
                None
                if not opening_text
                else parse_money_magnitude(
                    opening_text,
                    self._database.currency(currency),
                )
            )
            account = self._account_setup.create_balance_account(
                book_id=book.id,
                account_type=account_type,
                name=name,
                currency_code=currency,
                tracking_start_date=str(payload.get("trackingStartDate", "")),
                tracking_start_time=(
                    str(payload["trackingStartTime"])
                    if payload.get("trackingStartTime")
                    else None
                ),
                placeholder=placeholder,
                opening_balance_minor=opening_minor,
                opening_balance_direction=(
                    str(payload.get("openingBalanceDirection", "")).strip().upper()
                    or None
                ),
            )
        else:
            raise ValidationError(
                "user-created items must be a balance account or income/expense category"
            )
        return {"id": account.id, "state": self.snapshot()}

    def create_expense(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        source_id = self._positive_id(payload.get("sourceAccountId"))
        category_id = self._positive_id(payload.get("categoryAccountId"))
        source = self._accounts.get_account(book.id, source_id)
        if source.type not in {"ASSET", "LIABILITY"} or source.currency_code is None:
            raise ValidationError("source must be a balance account")
        amount = parse_money_magnitude(
            payload.get("amount", ""), self._database.currency(source.currency_code)
        )
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
            self._assign_optional_payee(conn, book.id, transaction.id, payload)
        return {"id": transaction.id, "state": self.snapshot()}

    def create_income(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        destination_id = self._positive_id(payload.get("destinationAccountId"))
        income_id = self._positive_id(payload.get("incomeAccountId"))
        destination = self._accounts.get_account(book.id, destination_id)
        if (
            destination.type not in {"ASSET", "LIABILITY"}
            or destination.currency_code is None
        ):
            raise ValidationError("destination must be a balance account")
        amount = parse_money_magnitude(
            payload.get("amount", ""),
            self._database.currency(destination.currency_code),
        )
        with self._database.transaction() as conn:
            transaction = self._ledger.create_income(
                book_id=book.id,
                destination_account_id=destination_id,
                income_account_id=income_id,
                amount_minor=amount,
                currency_code=destination.currency_code,
                transaction_date=str(payload.get("date", "")),
                transaction_time=str(payload["time"]) if payload.get("time") else None,
                description=str(payload.get("description", "")).strip(),
                connection=conn,
            )
            self._assign_optional_payee(conn, book.id, transaction.id, payload)
        return {"id": transaction.id, "state": self.snapshot()}

    def create_transfer(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        source_id = self._positive_id(payload.get("sourceAccountId"))
        destination_id = self._positive_id(payload.get("destinationAccountId"))
        source = self._accounts.get_account(book.id, source_id)
        if source.type not in {"ASSET", "LIABILITY"} or source.currency_code is None:
            raise ValidationError("source must be a balance account")
        amount = parse_money_magnitude(
            payload.get("amount", ""), self._database.currency(source.currency_code)
        )
        with self._database.transaction() as conn:
            transaction = self._ledger.create_transfer(
                book_id=book.id,
                source_account_id=source_id,
                destination_account_id=destination_id,
                amount_minor=amount,
                currency_code=source.currency_code,
                transaction_date=str(payload.get("date", "")),
                transaction_time=str(payload["time"]) if payload.get("time") else None,
                description=str(payload.get("description", "")).strip(),
                connection=conn,
            )
            self._assign_optional_payee(conn, book.id, transaction.id, payload)
        return {"id": transaction.id, "state": self.snapshot()}

    def _assign_optional_payee(
        self, conn, book_id: int, transaction_id: int, payload: dict[str, object]
    ) -> None:
        payee_id = payload.get("payeeId")
        if payee_id in (None, ""):
            return
        self._payees.assign_transaction(
            book_id=book_id,
            transaction_id=transaction_id,
            payee_id=self._positive_id(payee_id),
            connection=conn,
        )

    def rename_account(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        account = self._accounts.get_account(book.id, self._positive_id(payload.get("accountId")))
        name = str(payload.get("name", ""))
        if account.type in {"EXPENSE", "INCOME"}:
            self._categories.rename_category(book.id, account.id, name)
        else:
            self._accounts.rename_account(book.id, account.id, name)
        return {"id": account.id, "state": self.snapshot()}

    def set_account_archived(self, payload: dict[str, object]) -> dict[str, object]:
        book = self._require_book()
        archived = payload.get("archived")
        if not isinstance(archived, bool):
            raise ValidationError("archived must be boolean")
        account = self._accounts.get_account(book.id, self._positive_id(payload.get("accountId")))
        if account.type in {"EXPENSE", "INCOME"}:
            self._categories.set_archived(book.id, account.id, archived)
        else:
            self._accounts.set_archived(book.id, account.id, archived)
        return {"id": account.id, "state": self.snapshot()}

    def reverse_transaction(self, payload: dict[str, object]) -> dict[str, object]:
        """Correct a posting by reversing it on its own date and time."""
        book = self._require_book()
        original = self._ledger.get_transaction(
            book.id, self._positive_id(payload.get("transactionId"))
        )
        reversal = self._ledger.create_reversal(
            book_id=book.id,
            transaction_id=original.id,
            transaction_date=original.transaction_date,
            transaction_time=original.transaction_time,
        )
        return {"id": reversal.id, "state": self.snapshot()}

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

    def currency_digits(self, currency_code: str) -> int:
        return self._database.currency(currency_code).minor_unit_digits

    def _require_book(self):
        book = self._books.current_book()
        if book is None:
            raise ValidationError("initial setup is required")
        return book

    @staticmethod
    def _positive_id(value: object) -> int:
        parsed = AppController._integer(value, "identifier")
        if not 1 <= parsed <= (1 << 63) - 1:
            raise ValidationError("invalid identifier")
        return parsed

    @staticmethod
    def _integer(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            raise ValidationError(f"invalid {field}")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"invalid {field}") from exc

    @staticmethod
    def error_payload(exc: Exception) -> dict[str, object]:
        if isinstance(exc, FinanceTrackerError):
            return {
                "ok": False,
                "error": {"code": type(exc).__name__, "message": str(exc)},
            }
        if isinstance(exc, (TypeError, ValueError)):
            return {
                "ok": False,
                "error": {
                    "code": "ValidationError",
                    "message": "Invalid input type or value",
                },
            }
        raise exc
