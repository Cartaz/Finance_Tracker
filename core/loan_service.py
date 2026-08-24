from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext

from core.account_service import Account, AccountService
from core.database import Database
from core.errors import LoanError
from core.ledger_service import EntryDraft, LedgerService, TransactionDraft

_MAX_TERM_MONTHS = 600
_MAX_ANNUAL_RATE_BPS = 100_000


@dataclass(frozen=True, slots=True)
class LoanRecord:
    id: int
    book_id: int
    name: str
    liability_account_id: int
    payment_account_id: int
    interest_expense_account_id: int
    currency_code: str
    original_principal_minor: int
    annual_rate_bps: int
    term_months: int
    first_due_date: str
    origination_transaction_id: int | None


class LoanService:
    """Own fixed-rate loan contracts while the ledger owns every balance.

    `loans` contains contract metadata only. Current principal is always derived
    from the linked liability account; it is never persisted as parallel state.
    """

    def __init__(
        self,
        database: Database,
        accounts: AccountService,
        ledger: LedgerService,
    ) -> None:
        self._database = database
        self._accounts = accounts
        self._ledger = ledger

    def creation_capabilities(self, book_id: int) -> dict[str, object]:
        """Return backend-owned valid targets for creating a loan contract."""
        accounts = self._accounts.list_accounts(book_id)
        linked = {
            int(row["liability_account_id"])
            for row in self._database.connection.execute(
                "SELECT liability_account_id FROM loans WHERE book_id=?",
                (book_id,),
            ).fetchall()
        }
        interest_accounts = [
            {"id": account.id, "name": account.name}
            for account in accounts
            if account.type == "EXPENSE" and not account.placeholder
        ]
        targets: list[dict[str, object]] = []
        for liability in accounts:
            if (
                liability.type != "LIABILITY"
                or liability.placeholder
                or liability.id in linked
                or liability.currency_code is None
            ):
                continue
            native = self._accounts.native_balance(book_id, liability.id)
            if native > 0:
                continue
            asset_ids = [
                account.id
                for account in accounts
                if account.type == "ASSET"
                and not account.placeholder
                and account.currency_code == liability.currency_code
            ]
            if not asset_ids or not interest_accounts:
                continue
            allowed_modes = (
                ["NEW_DISBURSEMENT"] if native == 0 else ["EXISTING_BALANCE"]
            )
            targets.append(
                {
                    "liabilityAccountId": liability.id,
                    "name": liability.name,
                    "currency": liability.currency_code,
                    "nativeBalanceMinor": native,
                    "allowedModes": allowed_modes,
                    "paymentAccountIds": asset_ids,
                    "fundingAccountIds": asset_ids,
                }
            )
        return {
            "targets": targets,
            "interestExpenseAccounts": interest_accounts,
        }

    def create_loan(
        self,
        *,
        book_id: int,
        name: str,
        liability_account_id: int,
        payment_account_id: int,
        interest_expense_account_id: int,
        annual_rate_bps: int,
        term_months: int,
        first_due_date: str,
        mode: str = "EXISTING_BALANCE",
        principal_minor: int | None = None,
        funding_account_id: int | None = None,
        start_date: str | None = None,
    ) -> LoanRecord:
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            raise LoanError("loan name cannot be empty")
        rate_bps = self._rate_bps(annual_rate_bps)
        term = self._term(term_months)
        first_due = self._parse_date(first_due_date, "first_due_date")

        liability = self._accounts.get_account(book_id, liability_account_id)
        payment = self._accounts.get_account(book_id, payment_account_id)
        interest = self._accounts.get_account(book_id, interest_expense_account_id)
        self._validate_contract_accounts(liability, payment, interest)
        if liability.currency_code is None:
            raise LoanError("loan liability has no native currency")

        normalized_mode = mode.strip().upper() if isinstance(mode, str) else ""
        if normalized_mode not in {"EXISTING_BALANCE", "NEW_DISBURSEMENT"}:
            raise LoanError("mode must be EXISTING_BALANCE or NEW_DISBURSEMENT")

        origination_transaction_id: int | None = None
        with self._database.transaction() as conn:
            if conn.execute(
                "SELECT 1 FROM loans WHERE book_id=? AND liability_account_id=?",
                (book_id, liability.id),
            ).fetchone() is not None:
                raise LoanError("liability account is already linked to a loan")

            if normalized_mode == "EXISTING_BALANCE":
                outstanding = self._outstanding_minor(book_id, liability.id)
                if outstanding <= 0:
                    raise LoanError(
                        "existing-balance loan requires a negative liability balance"
                    )
                original_principal = outstanding
            else:
                if (
                    isinstance(principal_minor, bool)
                    or not isinstance(principal_minor, int)
                    or principal_minor <= 0
                ):
                    raise LoanError("principal_minor must be a positive integer")
                if funding_account_id is None:
                    raise LoanError("new disbursement requires a funding account")
                if start_date is None:
                    raise LoanError("new disbursement requires start_date")
                start = self._parse_date(start_date, "start_date")
                if first_due <= start:
                    raise LoanError("first_due_date must follow start_date")
                if self._accounts.native_balance(book_id, liability.id) != 0:
                    raise LoanError(
                        "new disbursement requires an empty liability account"
                    )
                funding = self._accounts.get_account(book_id, funding_account_id)
                self._validate_funding_account(funding, liability.currency_code)
                transaction = self._ledger.create_transfer(
                    book_id=book_id,
                    source_account_id=liability.id,
                    destination_account_id=funding.id,
                    amount_minor=principal_minor,
                    currency_code=liability.currency_code,
                    transaction_date=start.isoformat(),
                    description=f"Loan disbursement · {clean_name}",
                    connection=conn,
                )
                original_principal = principal_minor
                origination_transaction_id = transaction.id

            loan_id = int(
                conn.execute(
                    """
                    INSERT INTO loans(
                        book_id, name, liability_account_id, payment_account_id,
                        interest_expense_account_id, currency_code,
                        original_principal_minor, annual_rate_bps, term_months,
                        first_due_date, origination_transaction_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                    """,
                    (
                        book_id,
                        clean_name,
                        liability.id,
                        payment.id,
                        interest.id,
                        liability.currency_code,
                        original_principal,
                        rate_bps,
                        term,
                        first_due.isoformat(),
                        origination_transaction_id,
                    ),
                ).lastrowid
            )
        return self.get_loan(book_id, loan_id)

    def get_loan(self, book_id: int, loan_id: int) -> LoanRecord:
        row = self._database.connection.execute(
            "SELECT * FROM loans WHERE id=? AND book_id=?",
            (loan_id, book_id),
        ).fetchone()
        if row is None:
            raise LoanError("unknown loan")
        return self._record(row)

    def list_loans(self, book_id: int) -> list[dict[str, object]]:
        rows = self._database.connection.execute(
            "SELECT * FROM loans WHERE book_id=? ORDER BY name COLLATE NOCASE, id",
            (book_id,),
        ).fetchall()
        return [self.status(book_id, int(row["id"])) for row in rows]

    def status(self, book_id: int, loan_id: int) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        outstanding = self._outstanding_minor(book_id, loan.liability_account_id)
        if outstanding > loan.original_principal_minor:
            raise LoanError("loan liability exceeds original principal")
        paid_count = self._payment_count(book_id, loan.id)
        if paid_count > loan.term_months:
            raise LoanError("loan payment history exceeds contractual term")
        if paid_count >= loan.term_months and outstanding > 0:
            raise LoanError("loan remains outstanding after contractual term")
        next_due = (
            None
            if outstanding == 0
            else self._due_date(loan.first_due_date, paid_count + 1).isoformat()
        )
        fixed_payment = self._fixed_payment_minor(
            loan.original_principal_minor,
            loan.annual_rate_bps,
            loan.term_months,
        )
        return {
            "id": loan.id,
            "name": loan.name,
            "currency": loan.currency_code,
            "liabilityAccountId": loan.liability_account_id,
            "paymentAccountId": loan.payment_account_id,
            "interestExpenseAccountId": loan.interest_expense_account_id,
            "originalPrincipalMinor": loan.original_principal_minor,
            "outstandingPrincipalMinor": outstanding,
            "annualRateBps": loan.annual_rate_bps,
            "termMonths": loan.term_months,
            "fixedPaymentMinor": fixed_payment,
            "paidInstallments": paid_count,
            "remainingInstallments": max(0, loan.term_months - paid_count),
            "firstDueDate": loan.first_due_date,
            "nextDueDate": next_due,
            "closed": outstanding == 0,
            "originationTransactionId": loan.origination_transaction_id,
        }

    def amortization_plan(self, book_id: int, loan_id: int) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        rows = self._contract_plan(loan)
        return {
            "loanId": loan.id,
            "currency": loan.currency_code,
            "fixedPaymentMinor": self._fixed_payment_minor(
                loan.original_principal_minor,
                loan.annual_rate_bps,
                loan.term_months,
            ),
            "rows": rows,
            "totalInterestMinor": sum(int(row["interestMinor"]) for row in rows),
            "totalPaidMinor": sum(int(row["paymentMinor"]) for row in rows),
        }

    def post_next_payment(self, *, book_id: int, loan_id: int) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        paid_count = self._payment_count(book_id, loan.id)
        if paid_count >= loan.term_months:
            raise LoanError("contractual term has no remaining installments")
        outstanding = self._outstanding_minor(book_id, loan.liability_account_id)
        if outstanding <= 0:
            raise LoanError("loan is already paid off")
        if outstanding > loan.original_principal_minor:
            raise LoanError("loan liability exceeds original principal")

        installment_number = paid_count + 1
        due = self._due_date(loan.first_due_date, installment_number)
        fixed_payment = self._fixed_payment_minor(
            loan.original_principal_minor,
            loan.annual_rate_bps,
            loan.term_months,
        )
        interest_minor = self._interest_minor(outstanding, loan.annual_rate_bps)
        principal_minor = min(outstanding, fixed_payment - interest_minor)
        if principal_minor <= 0:
            raise LoanError("contract payment does not amortize principal")
        payment_minor = principal_minor + interest_minor

        with self._database.transaction() as conn:
            if interest_minor == 0:
                transaction = self._ledger.create_transfer(
                    book_id=book_id,
                    source_account_id=loan.payment_account_id,
                    destination_account_id=loan.liability_account_id,
                    amount_minor=principal_minor,
                    currency_code=loan.currency_code,
                    transaction_date=due.isoformat(),
                    description=f"Loan payment · {loan.name}",
                    connection=conn,
                )
            else:
                transaction = self._ledger.create_transaction(
                    TransactionDraft(
                        book_id=book_id,
                        kind="EXPENSE",
                        transaction_date=due.isoformat(),
                        currency_code=loan.currency_code,
                        description=f"Loan payment · {loan.name}",
                        entries=(
                            EntryDraft(
                                loan.payment_account_id,
                                -payment_minor,
                                -payment_minor,
                                "Loan payment",
                            ),
                            EntryDraft(
                                loan.liability_account_id,
                                principal_minor,
                                principal_minor,
                                "Principal",
                            ),
                            EntryDraft(
                                loan.interest_expense_account_id,
                                interest_minor,
                                None,
                                "Interest",
                            ),
                        ),
                    ),
                    connection=conn,
                )
            conn.execute(
                """
                INSERT INTO loan_payments(
                    loan_id, book_id, installment_number, due_date,
                    principal_minor, interest_minor, payment_minor,
                    transaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    loan.id,
                    book_id,
                    installment_number,
                    due.isoformat(),
                    principal_minor,
                    interest_minor,
                    payment_minor,
                    transaction.id,
                ),
            )
        return {
            "loanId": loan.id,
            "installmentNumber": installment_number,
            "dueDate": due.isoformat(),
            "principalMinor": principal_minor,
            "interestMinor": interest_minor,
            "paymentMinor": payment_minor,
            "transactionId": transaction.id,
            "status": self.status(book_id, loan.id),
        }

    def list_payments(self, book_id: int, loan_id: int) -> list[dict[str, object]]:
        self.get_loan(book_id, loan_id)
        rows = self._database.connection.execute(
            """
            SELECT installment_number, due_date, principal_minor, interest_minor,
                   payment_minor, transaction_id
            FROM loan_payments
            WHERE book_id=? AND loan_id=?
            ORDER BY installment_number
            """,
            (book_id, loan_id),
        ).fetchall()
        return [
            {
                "installmentNumber": int(row["installment_number"]),
                "dueDate": str(row["due_date"]),
                "principalMinor": int(row["principal_minor"]),
                "interestMinor": int(row["interest_minor"]),
                "paymentMinor": int(row["payment_minor"]),
                "transactionId": int(row["transaction_id"]),
            }
            for row in rows
        ]

    def _validate_live_contract(self, loan: LoanRecord) -> None:
        liability = self._accounts.get_account(loan.book_id, loan.liability_account_id)
        payment = self._accounts.get_account(loan.book_id, loan.payment_account_id)
        interest = self._accounts.get_account(
            loan.book_id, loan.interest_expense_account_id
        )
        self._validate_contract_accounts(liability, payment, interest)
        if liability.currency_code != loan.currency_code:
            raise LoanError("loan liability currency changed")
        if payment.currency_code != loan.currency_code:
            raise LoanError("loan payment account currency changed")
        native = self._accounts.native_balance(loan.book_id, liability.id)
        if native > 0:
            raise LoanError("loan liability has a positive balance")

    @staticmethod
    def _validate_contract_accounts(
        liability: Account,
        payment: Account,
        interest: Account,
    ) -> None:
        if liability.archived or liability.placeholder or liability.type != "LIABILITY":
            raise LoanError("loan account must be an active selectable LIABILITY")
        if payment.archived or payment.placeholder or payment.type != "ASSET":
            raise LoanError("payment account must be an active selectable ASSET")
        if interest.archived or interest.placeholder or interest.type != "EXPENSE":
            raise LoanError("interest account must be an active selectable EXPENSE")
        if liability.currency_code is None or payment.currency_code != liability.currency_code:
            raise LoanError("loan and payment account must use the same currency")

    @staticmethod
    def _validate_funding_account(account: Account, currency_code: str) -> None:
        if account.archived or account.placeholder or account.type != "ASSET":
            raise LoanError("funding account must be an active selectable ASSET")
        if account.currency_code != currency_code:
            raise LoanError("funding account must use the loan currency")

    def _outstanding_minor(self, book_id: int, liability_account_id: int) -> int:
        native = self._accounts.native_balance(book_id, liability_account_id)
        if native > 0:
            raise LoanError("loan liability has a positive balance")
        return -native

    def _payment_count(self, book_id: int, loan_id: int) -> int:
        return int(
            self._database.connection.execute(
                "SELECT COUNT(*) FROM loan_payments WHERE book_id=? AND loan_id=?",
                (book_id, loan_id),
            ).fetchone()[0]
        )

    @classmethod
    def _contract_plan(cls, loan: LoanRecord) -> list[dict[str, object]]:
        fixed = cls._fixed_payment_minor(
            loan.original_principal_minor,
            loan.annual_rate_bps,
            loan.term_months,
        )
        balance = loan.original_principal_minor
        rows: list[dict[str, object]] = []
        for installment_number in range(1, loan.term_months + 1):
            interest = cls._interest_minor(balance, loan.annual_rate_bps)
            principal = min(balance, fixed - interest)
            if installment_number == loan.term_months:
                principal = balance
            if principal <= 0:
                raise LoanError("contract payment does not amortize principal")
            payment = principal + interest
            balance -= principal
            rows.append(
                {
                    "installmentNumber": installment_number,
                    "dueDate": cls._due_date(
                        loan.first_due_date, installment_number
                    ).isoformat(),
                    "principalMinor": principal,
                    "interestMinor": interest,
                    "paymentMinor": payment,
                    "remainingPrincipalMinor": balance,
                }
            )
        return rows

    @staticmethod
    def _fixed_payment_minor(
        principal_minor: int,
        annual_rate_bps: int,
        term_months: int,
    ) -> int:
        if annual_rate_bps == 0:
            return max(
                1,
                int(
                    (Decimal(principal_minor) / Decimal(term_months)).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                ),
            )
        with localcontext() as context:
            context.prec = 50
            monthly_rate = Decimal(annual_rate_bps) / Decimal(10_000) / Decimal(12)
            factor = (Decimal(1) + monthly_rate) ** (-term_months)
            payment = Decimal(principal_minor) * monthly_rate / (Decimal(1) - factor)
            return max(1, int(payment.quantize(Decimal(1), rounding=ROUND_HALF_UP)))

    @staticmethod
    def _interest_minor(balance_minor: int, annual_rate_bps: int) -> int:
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
            return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))

    @staticmethod
    def _due_date(first_due_date: str, installment_number: int) -> date:
        anchor = date.fromisoformat(first_due_date)
        month_index = anchor.year * 12 + anchor.month - 1 + installment_number - 1
        year, zero_month = divmod(month_index, 12)
        month = zero_month + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)

    @staticmethod
    def _parse_date(value: str, field: str) -> date:
        if not isinstance(value, str):
            raise LoanError(f"invalid {field}")
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise LoanError(f"invalid {field}") from exc

    @staticmethod
    def _rate_bps(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 <= value <= _MAX_ANNUAL_RATE_BPS
        ):
            raise LoanError(
                f"annual_rate_bps must be between 0 and {_MAX_ANNUAL_RATE_BPS}"
            )
        return value

    @staticmethod
    def _term(value: int) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 1 <= value <= _MAX_TERM_MONTHS
        ):
            raise LoanError(f"term_months must be between 1 and {_MAX_TERM_MONTHS}")
        return value

    @staticmethod
    def _record(row) -> LoanRecord:
        return LoanRecord(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            name=str(row["name"]),
            liability_account_id=int(row["liability_account_id"]),
            payment_account_id=int(row["payment_account_id"]),
            interest_expense_account_id=int(row["interest_expense_account_id"]),
            currency_code=str(row["currency_code"]),
            original_principal_minor=int(row["original_principal_minor"]),
            annual_rate_bps=int(row["annual_rate_bps"]),
            term_months=int(row["term_months"]),
            first_due_date=str(row["first_due_date"]),
            origination_transaction_id=(
                None
                if row["origination_transaction_id"] is None
                else int(row["origination_transaction_id"])
            ),
        )
