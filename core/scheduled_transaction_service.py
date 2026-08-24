from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from core.account_service import AccountService
from core.database import Database
from core.errors import ScheduledTransactionError
from core.ledger_service import EntryDraft, LedgerService, TransactionDraft
from core.payee_service import PayeeService

_FREQUENCIES = {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}
_KINDS = {"EXPENSE", "INCOME", "REFUND", "TRANSFER"}


@dataclass(frozen=True, slots=True)
class ScheduledTransaction:
    id: int
    book_id: int
    kind: str
    source_account_id: int
    counter_account_id: int
    amount_minor: int
    currency_code: str
    frequency: str
    interval: int
    start_date: str
    next_due_date: str
    end_date: str | None
    description: str
    payee_id: int | None
    active: bool


class ScheduledTransactionService:
    """Own recurring templates while delegating every ledger write to LedgerService."""

    def __init__(
        self,
        database: Database,
        accounts: AccountService,
        ledger: LedgerService,
        payees: PayeeService,
    ) -> None:
        self._database = database
        self._accounts = accounts
        self._ledger = ledger
        self._payees = payees

    def create_schedule(
        self,
        *,
        book_id: int,
        kind: str,
        source_account_id: int,
        counter_account_id: int,
        amount_minor: int,
        frequency: str,
        interval: int,
        start_date: str,
        end_date: str | None = None,
        description: str = "",
        payee_id: int | None = None,
    ) -> ScheduledTransaction:
        normalized_kind = self._normalize_kind(kind)
        normalized_frequency = self._normalize_frequency(frequency)
        if isinstance(interval, bool) or not isinstance(interval, int) or not 1 <= interval <= 365:
            raise ScheduledTransactionError("interval must be between 1 and 365")
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ScheduledTransactionError("amount_minor must be a positive integer")
        start = self._parse_date(start_date, "start_date")
        end = None if end_date in (None, "") else self._parse_date(str(end_date), "end_date")
        if end is not None and end < start:
            raise ScheduledTransactionError("end_date cannot precede start_date")

        source = self._accounts.get_account(book_id, source_account_id)
        counter = self._accounts.get_account(book_id, counter_account_id)
        self._validate_accounts(normalized_kind, source, counter)
        if source.currency_code is None:
            raise ScheduledTransactionError("source account has no native currency")
        balance_accounts = (source, counter) if normalized_kind == "TRANSFER" else (source,)
        for account in balance_accounts:
            tracking_start = date.fromisoformat(account.tracking_start_date)
            if start <= tracking_start:
                raise ScheduledTransactionError(
                    f"scheduled start_date must be after account {account.id} tracking boundary"
                )
        if payee_id is not None:
            payee = self._payees.get_payee(book_id, payee_id)
            if payee.archived:
                raise ScheduledTransactionError("payee must be active")

        with self._database.transaction() as conn:
            schedule_id = int(
                conn.execute(
                    """
                    INSERT INTO scheduled_transactions(
                        book_id, kind, source_account_id, counter_account_id,
                        amount_minor, currency_code, frequency, interval_count,
                        start_date, next_due_date, end_date, description, payee_id,
                        active, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1,
                              datetime('now'), datetime('now'))
                    """,
                    (
                        book_id,
                        normalized_kind,
                        source.id,
                        counter.id,
                        amount_minor,
                        source.currency_code,
                        normalized_frequency,
                        interval,
                        start.isoformat(),
                        start.isoformat(),
                        None if end is None else end.isoformat(),
                        description.strip(),
                        payee_id,
                    ),
                ).lastrowid
            )
        return self.get_schedule(book_id, schedule_id)

    def get_schedule(self, book_id: int, schedule_id: int) -> ScheduledTransaction:
        row = self._database.connection.execute(
            "SELECT * FROM scheduled_transactions WHERE id=? AND book_id=?",
            (schedule_id, book_id),
        ).fetchone()
        if row is None:
            raise ScheduledTransactionError("unknown scheduled transaction")
        return self._record(row)

    def list_schedules(
        self, book_id: int, *, include_inactive: bool = True
    ) -> list[ScheduledTransaction]:
        clause = "" if include_inactive else " AND active=1"
        rows = self._database.connection.execute(
            f"SELECT * FROM scheduled_transactions WHERE book_id=?{clause} ORDER BY next_due_date, id",
            (book_id,),
        ).fetchall()
        return [self._record(row) for row in rows]

    def set_active(
        self, book_id: int, schedule_id: int, active: bool
    ) -> ScheduledTransaction:
        if not isinstance(active, bool):
            raise ScheduledTransactionError("active must be boolean")
        schedule = self.get_schedule(book_id, schedule_id)
        if (
            active
            and schedule.end_date is not None
            and date.fromisoformat(schedule.next_due_date)
            > date.fromisoformat(schedule.end_date)
        ):
            raise ScheduledTransactionError("completed schedule cannot be reactivated")
        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE scheduled_transactions SET active=?, updated_at=datetime('now') WHERE id=? AND book_id=?",
                (1 if active else 0, schedule_id, book_id),
            )
        return self.get_schedule(book_id, schedule_id)

    def post_due(
        self,
        *,
        book_id: int,
        as_of_date: str,
        schedule_id: int | None = None,
        max_occurrences: int = 1000,
    ) -> list[dict[str, object]]:
        as_of = self._parse_date(as_of_date, "as_of_date")
        if (
            isinstance(max_occurrences, bool)
            or not isinstance(max_occurrences, int)
            or not 1 <= max_occurrences <= 10_000
        ):
            raise ScheduledTransactionError(
                "max_occurrences must be between 1 and 10000"
            )
        schedules = (
            [self.get_schedule(book_id, schedule_id)]
            if schedule_id is not None
            else self.list_schedules(book_id, include_inactive=False)
        )
        due_count = sum(self._count_due(item, as_of) for item in schedules if item.active)
        if due_count > max_occurrences:
            raise ScheduledTransactionError("due occurrence limit reached")

        posted: list[dict[str, object]] = []
        with self._database.transaction() as conn:
            for schedule in schedules:
                if not schedule.active:
                    continue
                current = date.fromisoformat(schedule.next_due_date)
                end = (
                    None
                    if schedule.end_date is None
                    else date.fromisoformat(schedule.end_date)
                )
                while current <= as_of and (end is None or current <= end):
                    posted.append(self._post_occurrence(schedule, current, conn))
                    schedule = self.get_schedule(book_id, schedule.id)
                    current = date.fromisoformat(schedule.next_due_date)
                    if not schedule.active:
                        break
        return posted

    def _count_due(self, schedule: ScheduledTransaction, as_of: date) -> int:
        current = date.fromisoformat(schedule.next_due_date)
        end = None if schedule.end_date is None else date.fromisoformat(schedule.end_date)
        count = 0
        while current <= as_of and (end is None or current <= end):
            count += 1
            if count > 10_000:
                return count
            current = self._advance(
                current, schedule.frequency, schedule.interval, schedule.start_date
            )
        return count

    def _post_occurrence(
        self,
        schedule: ScheduledTransaction,
        due: date,
        conn,
    ) -> dict[str, object]:
        existing = conn.execute(
            "SELECT transaction_id FROM scheduled_occurrences WHERE schedule_id=? AND due_date=?",
            (schedule.id, due.isoformat()),
        ).fetchone()
        if existing is not None:
            next_due = self._advance(
                due, schedule.frequency, schedule.interval, schedule.start_date
            )
            self._advance_schedule(schedule, next_due, conn)
            return {
                "scheduleId": schedule.id,
                "dueDate": due.isoformat(),
                "transactionId": int(existing["transaction_id"]),
                "alreadyPosted": True,
            }

        source = self._accounts.get_account(schedule.book_id, schedule.source_account_id)
        counter = self._accounts.get_account(schedule.book_id, schedule.counter_account_id)
        self._validate_accounts(schedule.kind, source, counter)
        if source.currency_code != schedule.currency_code:
            raise ScheduledTransactionError("source account currency changed")
        next_due = self._advance(
            due, schedule.frequency, schedule.interval, schedule.start_date
        )
        amount = schedule.amount_minor
        if schedule.kind == "EXPENSE":
            entries = (
                EntryDraft(source.id, -amount, -amount),
                EntryDraft(counter.id, amount, None),
            )
        elif schedule.kind in {"INCOME", "REFUND"}:
            entries = (
                EntryDraft(source.id, amount, amount),
                EntryDraft(counter.id, -amount, None),
            )
        else:
            entries = (
                EntryDraft(source.id, -amount, -amount),
                EntryDraft(counter.id, amount, amount),
            )
        draft = TransactionDraft(
            book_id=schedule.book_id,
            kind=schedule.kind,
            transaction_date=due.isoformat(),
            currency_code=schedule.currency_code,
            description=schedule.description,
            entries=entries,
        )

        transaction = self._ledger.create_transaction(draft, connection=conn)
        if schedule.payee_id is not None:
            self._payees.assign_transaction(
                book_id=schedule.book_id,
                transaction_id=transaction.id,
                payee_id=schedule.payee_id,
                connection=conn,
            )
        conn.execute(
            """
            INSERT INTO scheduled_occurrences(
                schedule_id, book_id, due_date, transaction_id, created_at
            ) VALUES (?, ?, ?, ?, datetime('now'))
            """,
            (schedule.id, schedule.book_id, due.isoformat(), transaction.id),
        )
        self._advance_schedule(schedule, next_due, conn)
        return {
            "scheduleId": schedule.id,
            "dueDate": due.isoformat(),
            "transactionId": transaction.id,
            "alreadyPosted": False,
        }

    def _advance_schedule(
        self, schedule: ScheduledTransaction, next_due: date, conn
    ) -> None:
        end = None if schedule.end_date is None else date.fromisoformat(schedule.end_date)
        active = 0 if end is not None and next_due > end else 1
        conn.execute(
            """
            UPDATE scheduled_transactions
            SET next_due_date=?, active=?, updated_at=datetime('now')
            WHERE id=? AND book_id=?
            """,
            (next_due.isoformat(), active, schedule.id, schedule.book_id),
        )

    @staticmethod
    def _advance(
        current: date, frequency: str, interval: int, anchor_date: str
    ) -> date:
        if frequency == "DAILY":
            return current + timedelta(days=interval)
        if frequency == "WEEKLY":
            return current + timedelta(weeks=interval)
        anchor = date.fromisoformat(anchor_date)
        if frequency == "MONTHLY":
            month_index = current.year * 12 + current.month - 1 + interval
            year, zero_month = divmod(month_index, 12)
            month = zero_month + 1
            day = min(anchor.day, calendar.monthrange(year, month)[1])
            return date(year, month, day)
        year = current.year + interval
        day = min(anchor.day, calendar.monthrange(year, anchor.month)[1])
        return date(year, anchor.month, day)

    @staticmethod
    def _parse_date(value: str, field: str) -> date:
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ScheduledTransactionError(f"invalid {field}") from exc

    @staticmethod
    def _normalize_kind(value: str) -> str:
        if not isinstance(value, str) or value.strip().upper() not in _KINDS:
            raise ScheduledTransactionError(
                "kind must be EXPENSE, INCOME, REFUND or TRANSFER"
            )
        return value.strip().upper()

    @staticmethod
    def _normalize_frequency(value: str) -> str:
        if not isinstance(value, str) or value.strip().upper() not in _FREQUENCIES:
            raise ScheduledTransactionError(
                "frequency must be DAILY, WEEKLY, MONTHLY or YEARLY"
            )
        return value.strip().upper()

    @staticmethod
    def _validate_accounts(kind: str, source, counter) -> None:
        for account in (source, counter):
            if account.archived or account.placeholder:
                raise ScheduledTransactionError(
                    "scheduled accounts must be active and selectable"
                )
        if source.type not in {"ASSET", "LIABILITY"} or source.currency_code is None:
            raise ScheduledTransactionError("source must be a balance account")
        if source.id == counter.id:
            raise ScheduledTransactionError("source and counter account must differ")
        if kind in {"EXPENSE", "REFUND"} and counter.type != "EXPENSE":
            raise ScheduledTransactionError(
                "expense/refund counter must be an expense category"
            )
        if kind == "INCOME" and counter.type != "INCOME":
            raise ScheduledTransactionError("income counter must be an income category")
        if kind == "TRANSFER":
            if counter.type not in {"ASSET", "LIABILITY"} or counter.currency_code is None:
                raise ScheduledTransactionError(
                    "transfer counter must be a balance account"
                )
            if counter.currency_code != source.currency_code:
                raise ScheduledTransactionError(
                    "scheduled cross-currency transfers are not inferred"
                )

    @staticmethod
    def _record(row) -> ScheduledTransaction:
        return ScheduledTransaction(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            kind=str(row["kind"]),
            source_account_id=int(row["source_account_id"]),
            counter_account_id=int(row["counter_account_id"]),
            amount_minor=int(row["amount_minor"]),
            currency_code=str(row["currency_code"]),
            frequency=str(row["frequency"]),
            interval=int(row["interval_count"]),
            start_date=str(row["start_date"]),
            next_due_date=str(row["next_due_date"]),
            end_date=None if row["end_date"] is None else str(row["end_date"]),
            description=str(row["description"]),
            payee_id=None if row["payee_id"] is None else int(row["payee_id"]),
            active=bool(row["active"]),
        )
