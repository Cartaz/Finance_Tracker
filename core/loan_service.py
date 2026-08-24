from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

from core.account_service import Account, AccountService
from core.database import Database
from core.errors import LoanError
from core.ledger_service import EntryDraft, LedgerService, TransactionDraft
from core.loan_policies import AmortizationPolicy
from core.tracking_policy import TrackingBoundaryPolicy, TrackingBoundaryStatus

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
    rate_type: str
    amortization_type: str
    recast_strategy: str


class LoanService:
    """Own loan contracts while LedgerService remains the accounting writer.

    Contract metadata and rate history are persisted. Outstanding principal is
    never shadow-persisted: it is always derived from the linked LIABILITY
    account. Plans and forecasts are deterministic projections of canonical
    ledger state plus contract/rate policy.
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
            if account.type == "EXPENSE"
            and not account.placeholder
            and not account.archived
        ]
        targets: list[dict[str, object]] = []
        for liability in accounts:
            if (
                liability.type != "LIABILITY"
                or liability.placeholder
                or liability.archived
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
                and not account.archived
                and account.currency_code == liability.currency_code
            ]
            if not asset_ids or not interest_accounts:
                continue
            targets.append(
                {
                    "liabilityAccountId": liability.id,
                    "name": liability.name,
                    "currency": liability.currency_code,
                    "nativeBalanceMinor": native,
                    "allowedModes": [
                        "NEW_DISBURSEMENT" if native == 0 else "EXISTING_BALANCE"
                    ],
                    "paymentAccountIds": asset_ids,
                    "fundingAccountIds": asset_ids,
                }
            )
        return {
            "targets": targets,
            "interestExpenseAccounts": interest_accounts,
            "rateTypes": ["FIXED", "VARIABLE"],
            "amortizationTypes": ["FRENCH", "ITALIAN", "BULLET"],
            "recastStrategies": ["REDUCE_PAYMENT", "REDUCE_TERM"],
            "policyCombinations": AmortizationPolicy.compatibility_payload(),
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
        rate_type: str = "FIXED",
        amortization_type: str = "FRENCH",
        recast_strategy: str = "REDUCE_PAYMENT",
    ) -> LoanRecord:
        clean_name = name.strip() if isinstance(name, str) else ""
        if not clean_name:
            raise LoanError("loan name cannot be empty")
        rate_bps = self._rate_bps(annual_rate_bps)
        term = self._term(term_months)
        first_due = self._parse_date(first_due_date, "first_due_date")
        normalized_rate_type = AmortizationPolicy.normalize_rate_type(rate_type)
        normalized_amortization = AmortizationPolicy.normalize_amortization(
            amortization_type
        )
        normalized_recast = AmortizationPolicy.normalize_recast_strategy(
            recast_strategy
        )
        AmortizationPolicy.validate_contract_policy(
            rate_type=normalized_rate_type,
            amortization_type=normalized_amortization,
            recast_strategy=normalized_recast,
        )

        liability = self._accounts.get_account(book_id, liability_account_id)
        payment = self._accounts.get_account(book_id, payment_account_id)
        interest = self._accounts.get_account(book_id, interest_expense_account_id)
        self._validate_contract_accounts(liability, payment, interest)
        self._validate_due_boundary(liability, first_due)
        self._validate_due_boundary(payment, first_due)
        if liability.currency_code is None:
            raise LoanError("loan liability has no native currency")

        normalized_mode = mode.strip().upper() if isinstance(mode, str) else ""
        if normalized_mode not in {"EXISTING_BALANCE", "NEW_DISBURSEMENT"}:
            raise LoanError("mode must be EXISTING_BALANCE or NEW_DISBURSEMENT")

        origination_transaction_id: int | None = None
        rate_effective_date = first_due.isoformat()
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
                rate_effective_date = start.isoformat()

            loan_id = int(
                conn.execute(
                    """
                    INSERT INTO loans(
                        book_id,name,liability_account_id,payment_account_id,
                        interest_expense_account_id,currency_code,
                        original_principal_minor,annual_rate_bps,term_months,
                        first_due_date,origination_transaction_id,
                        rate_type,amortization_type,recast_strategy,
                        created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),datetime('now'))
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
                        normalized_rate_type,
                        normalized_amortization,
                        normalized_recast,
                    ),
                ).lastrowid
            )
            if normalized_rate_type == "VARIABLE":
                conn.execute(
                    """
                    INSERT INTO loan_rate_revisions(
                        loan_id,book_id,effective_date,annual_rate_bps,created_at
                    ) VALUES (?,?,?,?,datetime('now'))
                    """,
                    (loan_id, book_id, rate_effective_date, rate_bps),
                )
        return self.get_loan(book_id, loan_id)

    def set_variable_rate(
        self,
        *,
        book_id: int,
        loan_id: int,
        effective_date: str,
        annual_rate_bps: int,
    ) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        if loan.rate_type != "VARIABLE":
            raise LoanError("rate revisions are only valid for VARIABLE loans")
        effective = self._parse_date(effective_date, "effective_date")
        rate = self._rate_bps(annual_rate_bps)
        posted = self._database.connection.execute(
            "SELECT MAX(due_date) FROM loan_payments WHERE book_id=? AND loan_id=?",
            (book_id, loan.id),
        ).fetchone()[0]
        if posted is not None and effective.isoformat() <= str(posted):
            raise LoanError("rate revision cannot rewrite a posted installment period")
        with self._database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO loan_rate_revisions(
                    loan_id,book_id,effective_date,annual_rate_bps,created_at
                ) VALUES (?,?,?,?,datetime('now'))
                ON CONFLICT(loan_id,effective_date) DO UPDATE SET
                    annual_rate_bps=excluded.annual_rate_bps,
                    created_at=excluded.created_at
                """,
                (loan.id, book_id, effective.isoformat(), rate),
            )
        return {
            "loanId": loan.id,
            "effectiveDate": effective.isoformat(),
            "annualRateBps": rate,
        }

    def list_rate_revisions(
        self, book_id: int, loan_id: int
    ) -> list[dict[str, object]]:
        loan = self.get_loan(book_id, loan_id)
        if loan.rate_type != "VARIABLE":
            return []
        rows = self._database.connection.execute(
            """
            SELECT effective_date,annual_rate_bps
            FROM loan_rate_revisions
            WHERE book_id=? AND loan_id=?
            ORDER BY effective_date
            """,
            (book_id, loan_id),
        ).fetchall()
        return [
            {
                "effectiveDate": str(row["effective_date"]),
                "annualRateBps": int(row["annual_rate_bps"]),
            }
            for row in rows
        ]

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
            "SELECT id FROM loans WHERE book_id=? ORDER BY name COLLATE NOCASE,id",
            (book_id,),
        ).fetchall()
        return [self.status(book_id, int(row["id"])) for row in rows]

    def status(self, book_id: int, loan_id: int) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        outstanding = self._validated_outstanding(loan)
        last_installment = self._last_installment_number(book_id, loan.id)
        if outstanding > 0 and last_installment >= loan.term_months:
            raise LoanError("contractual term ended with outstanding principal")
        next_terms = (
            None
            if outstanding == 0
            else self._next_actual_terms(loan, outstanding, last_installment + 1)
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
            "currentAnnualRateBps": (
                None if next_terms is None else int(next_terms[5])
            ),
            "rateType": loan.rate_type,
            "ratePolicy": (
                "FIXED_CONTRACT"
                if loan.rate_type == "FIXED"
                else "LATEST_EFFECTIVE_REVISION"
            ),
            "amortizationType": loan.amortization_type,
            "recastStrategy": loan.recast_strategy,
            "termMonths": loan.term_months,
            "fixedPaymentMinor": 0 if next_terms is None else int(next_terms[4]),
            "nextPaymentMinor": 0 if next_terms is None else int(next_terms[4]),
            "paidInstallments": self._payment_count(book_id, loan.id),
            "lastInstallmentNumber": last_installment,
            "remainingInstallments": max(0, loan.term_months - last_installment),
            "firstDueDate": loan.first_due_date,
            "nextDueDate": None if next_terms is None else next_terms[0].isoformat(),
            "closed": outstanding == 0,
            "originationTransactionId": loan.origination_transaction_id,
        }

    def amortization_plan(self, book_id: int, loan_id: int) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        outstanding = self._validated_outstanding(loan)
        last_installment = self._last_installment_number(book_id, loan.id)
        rows = self._project_remaining_rows(loan, outstanding, last_installment + 1)
        return {
            "loanId": loan.id,
            "currency": loan.currency_code,
            "rateType": loan.rate_type,
            "ratePolicy": (
                "FIXED_CONTRACT"
                if loan.rate_type == "FIXED"
                else "LATEST_EFFECTIVE_REVISION"
            ),
            "amortizationType": loan.amortization_type,
            "recastStrategy": loan.recast_strategy,
            "planBasis": "CURRENT_LEDGER_STATE",
            "rows": rows,
            "totalInterestMinor": sum(int(row["interestMinor"]) for row in rows),
            "totalPaidMinor": sum(int(row["paymentMinor"]) for row in rows),
        }

    def project_payments(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, object]]:
        start = self._parse_date(start_date, "start_date")
        end = self._parse_date(end_date, "end_date")
        if end < start:
            raise LoanError("end_date cannot precede start_date")
        projected: list[dict[str, object]] = []
        for item in self.list_loans(book_id):
            if bool(item["closed"]):
                continue
            loan = self.get_loan(book_id, int(item["id"]))
            outstanding = int(item["outstandingPrincipalMinor"])
            start_installment = int(item["lastInstallmentNumber"]) + 1
            for row in self._project_remaining_rows(
                loan, outstanding, start_installment
            ):
                due = date.fromisoformat(str(row["dueDate"]))
                if due > end:
                    break
                if due >= start and int(row["paymentMinor"]) > 0:
                    projected.append(
                        {
                            "source": "LOAN_INSTALLMENT",
                            "loanId": loan.id,
                            "installmentNumber": int(row["installmentNumber"]),
                            "dueDate": row["dueDate"],
                            "amountMinor": int(row["paymentMinor"]),
                            "principalMinor": int(row["principalMinor"]),
                            "interestMinor": int(row["interestMinor"]),
                            "annualRateBps": int(row["annualRateBps"]),
                            "currency": loan.currency_code,
                            "description": f"Loan payment · {loan.name}",
                        }
                    )
        projected.sort(
            key=lambda item: (
                str(item["dueDate"]),
                int(item["loanId"]),
                int(item["installmentNumber"]),
            )
        )
        return projected

    def post_next_payment(self, *, book_id: int, loan_id: int) -> dict[str, object]:
        return self._post_payment(
            book_id=book_id, loan_id=loan_id, custom_amount_minor=None
        )

    def post_custom_payment(
        self,
        *,
        book_id: int,
        loan_id: int,
        amount_minor: int,
        recast_strategy: str | None = None,
    ) -> dict[str, object]:
        if (
            isinstance(amount_minor, bool)
            or not isinstance(amount_minor, int)
            or amount_minor <= 0
        ):
            raise LoanError("custom payment must be a positive integer magnitude")
        return self._post_payment(
            book_id=book_id,
            loan_id=loan_id,
            custom_amount_minor=amount_minor,
            recast_strategy=recast_strategy,
        )

    def _post_payment(
        self,
        *,
        book_id: int,
        loan_id: int,
        custom_amount_minor: int | None,
        recast_strategy: str | None = None,
    ) -> dict[str, object]:
        loan = self.get_loan(book_id, loan_id)
        self._validate_live_contract(loan)
        outstanding = self._validated_outstanding(loan)
        if outstanding <= 0:
            raise LoanError("loan is already paid off")
        next_terms = self._next_actual_terms(
            loan,
            outstanding,
            self._last_installment_number(book_id, loan.id) + 1,
        )
        (
            due,
            installment_number,
            scheduled_principal,
            interest,
            scheduled_payment,
            rate,
        ) = next_terms
        strategy = loan.recast_strategy
        payment_kind = "REGULAR"
        principal = scheduled_principal
        payment = scheduled_payment

        if custom_amount_minor is not None:
            payment_kind = "CUSTOM"
            if recast_strategy is not None:
                strategy = AmortizationPolicy.normalize_recast_strategy(recast_strategy)
            AmortizationPolicy.validate_contract_policy(
                rate_type=loan.rate_type,
                amortization_type=loan.amortization_type,
                recast_strategy=strategy,
            )
            if custom_amount_minor < scheduled_payment:
                raise LoanError(
                    "custom payment below the scheduled payment requires arrears semantics"
                )
            if custom_amount_minor > outstanding + interest:
                raise LoanError(
                    "custom payment exceeds outstanding principal plus interest"
                )
            principal = custom_amount_minor - interest
            if principal <= 0:
                raise LoanError(
                    "custom payment must cover accrued interest and reduce principal"
                )
            payment = custom_amount_minor

        with self._database.transaction() as conn:
            transaction = self._post_ledger_payment(
                loan=loan,
                due=due,
                principal_minor=principal,
                interest_minor=interest,
                payment_minor=payment,
                connection=conn,
            )
            conn.execute(
                """
                INSERT INTO loan_payments(
                    loan_id,book_id,installment_number,due_date,
                    principal_minor,interest_minor,payment_minor,annual_rate_bps,
                    payment_kind,recast_strategy,transaction_id,created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                """,
                (
                    loan.id,
                    book_id,
                    installment_number,
                    due.isoformat(),
                    principal,
                    interest,
                    payment,
                    rate,
                    payment_kind,
                    strategy if payment_kind == "CUSTOM" else None,
                    transaction.id,
                ),
            )
            if payment_kind == "CUSTOM" and strategy != loan.recast_strategy:
                conn.execute(
                    "UPDATE loans SET recast_strategy=?,updated_at=datetime('now') WHERE id=? AND book_id=?",
                    (strategy, loan.id, book_id),
                )
        return {
            "loanId": loan.id,
            "installmentNumber": installment_number,
            "dueDate": due.isoformat(),
            "principalMinor": principal,
            "interestMinor": interest,
            "paymentMinor": payment,
            "annualRateBps": rate,
            "paymentKind": payment_kind,
            "recastStrategy": strategy if payment_kind == "CUSTOM" else None,
            "transactionId": transaction.id,
            "status": self.status(book_id, loan.id),
        }

    def list_payments(self, book_id: int, loan_id: int) -> list[dict[str, object]]:
        self.get_loan(book_id, loan_id)
        rows = self._database.connection.execute(
            """
            SELECT installment_number,due_date,principal_minor,interest_minor,
                   payment_minor,annual_rate_bps,payment_kind,recast_strategy,transaction_id
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
                "annualRateBps": int(row["annual_rate_bps"]),
                "paymentKind": str(row["payment_kind"]),
                "recastStrategy": row["recast_strategy"],
                "transactionId": int(row["transaction_id"]),
            }
            for row in rows
        ]

    def _project_remaining_rows(
        self,
        loan: LoanRecord,
        outstanding_minor: int,
        start_installment: int,
    ) -> list[dict[str, object]]:
        if outstanding_minor == 0:
            return []
        outstanding = outstanding_minor
        rows: list[dict[str, object]] = []
        for installment_number in range(start_installment, loan.term_months + 1):
            due = self._due_date(loan.first_due_date, installment_number)
            rate = self._rate_for_due(loan, due)
            remaining = loan.term_months - installment_number + 1
            fixed = self._french_fixed_payment(loan, outstanding, remaining, rate)
            terms = AmortizationPolicy.installment(
                amortization_type=loan.amortization_type,
                outstanding_minor=outstanding,
                annual_rate_bps=rate,
                remaining_installments=remaining,
                original_principal_minor=loan.original_principal_minor,
                original_term_months=loan.term_months,
                installment_number=installment_number,
                recast_strategy=loan.recast_strategy,
                fixed_french_payment_minor=fixed,
            )
            outstanding -= terms.principal_minor
            rows.append(
                {
                    "installmentNumber": installment_number,
                    "dueDate": due.isoformat(),
                    "annualRateBps": rate,
                    "principalMinor": terms.principal_minor,
                    "interestMinor": terms.interest_minor,
                    "paymentMinor": terms.payment_minor,
                    "remainingPrincipalMinor": outstanding,
                }
            )
            if outstanding == 0:
                break
        if outstanding > 0:
            raise LoanError(
                "contractual term cannot amortize current outstanding principal"
            )
        return rows

    def _next_actual_terms(
        self,
        loan: LoanRecord,
        outstanding_minor: int,
        start_installment: int,
    ) -> tuple[date, int, int, int, int, int]:
        for row in self._project_remaining_rows(
            loan, outstanding_minor, start_installment
        ):
            if int(row["paymentMinor"]) <= 0:
                continue
            return (
                date.fromisoformat(str(row["dueDate"])),
                int(row["installmentNumber"]),
                int(row["principalMinor"]),
                int(row["interestMinor"]),
                int(row["paymentMinor"]),
                int(row["annualRateBps"]),
            )
        raise LoanError("loan has no payable installment remaining")

    def _french_fixed_payment(
        self,
        loan: LoanRecord,
        outstanding_minor: int,
        remaining_installments: int,
        rate_bps: int,
    ) -> int | None:
        if loan.amortization_type != "FRENCH":
            return None
        if loan.rate_type == "VARIABLE":
            return None
        if loan.recast_strategy == "REDUCE_PAYMENT" and self._has_custom_payment(
            loan.book_id, loan.id
        ):
            return None
        return AmortizationPolicy.french_payment_minor(
            loan.original_principal_minor,
            loan.annual_rate_bps,
            loan.term_months,
        )

    def _rate_for_due(self, loan: LoanRecord, due: date) -> int:
        if loan.rate_type == "FIXED":
            return loan.annual_rate_bps
        row = self._database.connection.execute(
            """
            SELECT annual_rate_bps FROM loan_rate_revisions
            WHERE book_id=? AND loan_id=? AND effective_date<=?
            ORDER BY effective_date DESC LIMIT 1
            """,
            (loan.book_id, loan.id, due.isoformat()),
        ).fetchone()
        if row is None:
            raise LoanError(
                f"missing variable rate for loan {loan.id} on {due.isoformat()}"
            )
        return int(row["annual_rate_bps"])

    def _post_ledger_payment(
        self,
        *,
        loan: LoanRecord,
        due: date,
        principal_minor: int,
        interest_minor: int,
        payment_minor: int,
        connection,
    ):
        if interest_minor == 0:
            return self._ledger.create_transfer(
                book_id=loan.book_id,
                source_account_id=loan.payment_account_id,
                destination_account_id=loan.liability_account_id,
                amount_minor=principal_minor,
                currency_code=loan.currency_code,
                transaction_date=due.isoformat(),
                description=f"Loan payment · {loan.name}",
                connection=connection,
            )
        entries = [
            EntryDraft(
                loan.payment_account_id,
                -payment_minor,
                -payment_minor,
                "Loan payment",
            ),
            EntryDraft(
                loan.interest_expense_account_id,
                interest_minor,
                None,
                "Interest",
            ),
        ]
        if principal_minor > 0:
            entries.insert(
                1,
                EntryDraft(
                    loan.liability_account_id,
                    principal_minor,
                    principal_minor,
                    "Principal",
                ),
            )
        return self._ledger.create_transaction(
            TransactionDraft(
                book_id=loan.book_id,
                kind="EXPENSE",
                transaction_date=due.isoformat(),
                currency_code=loan.currency_code,
                description=f"Loan payment · {loan.name}",
                entries=tuple(entries),
            ),
            connection=connection,
        )

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
        outstanding = self._outstanding_minor(loan.book_id, liability.id)
        if outstanding > loan.original_principal_minor:
            raise LoanError("loan liability exceeds original contractual principal")

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
        if (
            liability.currency_code is None
            or payment.currency_code != liability.currency_code
        ):
            raise LoanError("loan and payment account must use the same currency")

    @staticmethod
    def _validate_funding_account(account: Account, currency_code: str) -> None:
        if account.archived or account.placeholder or account.type != "ASSET":
            raise LoanError("funding account must be an active selectable ASSET")
        if account.currency_code != currency_code:
            raise LoanError("funding account must use the loan currency")

    @staticmethod
    def _validate_due_boundary(account: Account, due: date) -> None:
        if account.tracking_start_date is None:
            return
        result = TrackingBoundaryPolicy.classify(
            tracking_start_date=account.tracking_start_date,
            tracking_start_time=account.tracking_start_time,
            transaction_date=due.isoformat(),
            transaction_time=None,
        )
        if result.status is TrackingBoundaryStatus.BEFORE_BOUNDARY:
            raise LoanError(
                "first loan installment precedes an account tracking boundary"
            )
        if result.status is TrackingBoundaryStatus.AMBIGUOUS:
            raise LoanError(
                "first loan installment is ambiguous against an account tracking boundary"
            )

    def _validated_outstanding(self, loan: LoanRecord) -> int:
        outstanding = self._outstanding_minor(
            loan.book_id, loan.liability_account_id
        )
        if outstanding > loan.original_principal_minor:
            raise LoanError("loan liability exceeds original contractual principal")
        return outstanding

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

    def _last_installment_number(self, book_id: int, loan_id: int) -> int:
        return int(
            self._database.connection.execute(
                "SELECT COALESCE(MAX(installment_number),0) FROM loan_payments WHERE book_id=? AND loan_id=?",
                (book_id, loan_id),
            ).fetchone()[0]
        )

    def _has_custom_payment(self, book_id: int, loan_id: int) -> bool:
        return (
            self._database.connection.execute(
                "SELECT 1 FROM loan_payments WHERE book_id=? AND loan_id=? AND payment_kind='CUSTOM' LIMIT 1",
                (book_id, loan_id),
            ).fetchone()
            is not None
        )

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
            rate_type=str(row["rate_type"]),
            amortization_type=str(row["amortization_type"]),
            recast_strategy=str(row["recast_strategy"]),
        )
