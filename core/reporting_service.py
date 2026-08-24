from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from core.account_service import AccountService
from core.category_service import CategoryService
from core.database import Database
from core.errors import FxRateMissingError, ReportingError
from core.fx_service import FxService


class ReportingService:
    """Read-only financial aggregation over the canonical ledger."""

    def __init__(
        self,
        database: Database,
        fx: FxService,
        accounts: AccountService | None = None,
        categories: CategoryService | None = None,
    ) -> None:
        self._database = database
        self._fx = fx
        self._accounts = accounts or AccountService(database)
        self._categories = categories or CategoryService(database, self._accounts)

    def dashboard(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        as_of_date: str,
    ) -> dict[str, object]:
        start, end = self._period(start_date, end_date)
        as_of = self._date(as_of_date, "as_of_date")
        base_currency = self._fx.base_currency(book_id)
        return {
            "baseCurrency": base_currency,
            "startDate": start,
            "endDate": end,
            "asOfDate": as_of,
            "overview": self.overview(
                book_id=book_id,
                start_date=start,
                end_date=end,
                as_of_date=as_of,
            ),
            "categories": self.category_report(
                book_id=book_id,
                start_date=start,
                end_date=end,
                category_type="EXPENSE",
                limit=8,
            ),
            "merchants": self.merchant_report(
                book_id=book_id,
                start_date=start,
                end_date=end,
                limit=8,
            ),
            "cashFlow": self.cash_flow(
                book_id=book_id,
                start_date=start,
                end_date=end,
                granularity="MONTH",
            ),
        }

    def overview(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        as_of_date: str,
    ) -> dict[str, object]:
        start, end = self._period(start_date, end_date)
        as_of = self._date(as_of_date, "as_of_date")
        balances = self._balance_overview(book_id, as_of)
        flows = self._period_totals(book_id, start, end)
        income = flows["incomeMinor"]
        expenses = flows["expenseMinor"]
        saving = None
        saving_rate = None
        if income is not None and expenses is not None:
            saving = int(income) - int(expenses)
            if int(income) > 0:
                saving_rate = int(
                    (Decimal(saving) * Decimal(10_000) / Decimal(int(income))).quantize(
                        Decimal(1), rounding=ROUND_HALF_UP
                    )
                )
        missing = self._merge_missing(
            balances["missingFx"],
            flows["missingFx"],
        )
        return {
            "baseCurrency": self._fx.base_currency(book_id),
            "startDate": start,
            "endDate": end,
            "asOfDate": as_of,
            "netWorthMinor": balances["netWorthMinor"],
            "assetsMinor": balances["assetsMinor"],
            "liabilitiesMinor": balances["liabilitiesMinor"],
            "netWorthComplete": balances["complete"],
            "accounts": balances["accounts"],
            "incomeMinor": income,
            "expenseMinor": expenses,
            "savingMinor": saving,
            "savingRateBps": saving_rate,
            "flowComplete": flows["complete"],
            "complete": bool(balances["complete"] and flows["complete"]),
            "missingFx": missing,
        }

    def category_report(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        category_type: str = "EXPENSE",
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        start, end = self._period(start_date, end_date)
        category_type = category_type.upper()
        if category_type not in {"EXPENSE", "INCOME"}:
            raise ReportingError("category_type must be EXPENSE or INCOME")
        self._validate_limit(limit)
        rows = self._flow_rows(book_id, start, end, account_type=category_type)
        grouped: dict[int, dict[str, object]] = {}
        for row in rows:
            account_id = int(row["account_id"])
            item = grouped.setdefault(
                account_id,
                {
                    "accountId": account_id,
                    "name": str(row["account_name"]),
                    "path": self._categories.category_path(book_id, account_id),
                    "amount": 0,
                    "complete": True,
                    "missing": set(),
                    "transactions": set(),
                },
            )
            converted = self._convert_row(book_id, row, item["missing"])
            if converted is None:
                item["complete"] = False
            else:
                economic = converted if category_type == "EXPENSE" else -converted
                item["amount"] = int(item["amount"]) + economic
            item["transactions"].add(int(row["transaction_id"]))

        result = [
            {
                "accountId": int(item["accountId"]),
                "name": str(item["name"]),
                "path": str(item["path"]),
                "amountMinor": int(item["amount"]) if item["complete"] else None,
                "transactionCount": len(item["transactions"]),
                "complete": bool(item["complete"]),
                "missingFx": self._missing_payload(item["missing"]),
            }
            for item in grouped.values()
        ]
        result.sort(
            key=lambda item: (
                item["amountMinor"] is None,
                -(int(item["amountMinor"]) if item["amountMinor"] is not None else 0),
                str(item["path"]).casefold(),
            )
        )
        return result if limit is None else result[:limit]

    def merchant_report(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        start, end = self._period(start_date, end_date)
        self._validate_limit(limit)
        rows = self._flow_rows(book_id, start, end, account_type="EXPENSE")
        grouped: dict[int | None, dict[str, object]] = {}
        for row in rows:
            payee_id = None if row["payee_id"] is None else int(row["payee_id"])
            item = grouped.setdefault(
                payee_id,
                {
                    "payeeId": payee_id,
                    "name": str(row["payee_name"] or "Senza merchant"),
                    "amount": 0,
                    "complete": True,
                    "missing": set(),
                    "transactions": set(),
                },
            )
            converted = self._convert_row(book_id, row, item["missing"])
            if converted is None:
                item["complete"] = False
            else:
                item["amount"] = int(item["amount"]) + converted
            item["transactions"].add(int(row["transaction_id"]))

        result = [
            {
                "payeeId": item["payeeId"],
                "name": str(item["name"]),
                "amountMinor": int(item["amount"]) if item["complete"] else None,
                "transactionCount": len(item["transactions"]),
                "complete": bool(item["complete"]),
                "missingFx": self._missing_payload(item["missing"]),
            }
            for item in grouped.values()
        ]
        result.sort(
            key=lambda item: (
                item["amountMinor"] is None,
                -(int(item["amountMinor"]) if item["amountMinor"] is not None else 0),
                str(item["name"]).casefold(),
            )
        )
        return result if limit is None else result[:limit]

    def cash_flow(
        self,
        *,
        book_id: int,
        start_date: str,
        end_date: str,
        granularity: str = "MONTH",
    ) -> list[dict[str, object]]:
        start, end = self._period(start_date, end_date)
        granularity = granularity.upper()
        if granularity not in {"DAY", "MONTH", "YEAR"}:
            raise ReportingError("granularity must be DAY, MONTH or YEAR")
        rows = self._flow_rows(book_id, start, end)
        buckets: dict[str, dict[str, object]] = defaultdict(
            lambda: {
                "income": 0,
                "expense": 0,
                "incomeComplete": True,
                "expenseComplete": True,
                "missing": set(),
            }
        )
        for row in rows:
            tx_date = str(row["transaction_date"])
            label = tx_date if granularity == "DAY" else tx_date[:7] if granularity == "MONTH" else tx_date[:4]
            bucket = buckets[label]
            converted = self._convert_row(book_id, row, bucket["missing"])
            account_type = str(row["account_type"])
            if converted is None:
                bucket[f"{account_type.lower()}Complete"] = False
                continue
            if account_type == "INCOME":
                bucket["income"] = int(bucket["income"]) - converted
            else:
                bucket["expense"] = int(bucket["expense"]) + converted

        result = []
        for label in sorted(buckets):
            bucket = buckets[label]
            income = int(bucket["income"]) if bucket["incomeComplete"] else None
            expense = int(bucket["expense"]) if bucket["expenseComplete"] else None
            result.append(
                {
                    "period": label,
                    "incomeMinor": income,
                    "expenseMinor": expense,
                    "netMinor": None if income is None or expense is None else income - expense,
                    "complete": bool(bucket["incomeComplete"] and bucket["expenseComplete"]),
                    "missingFx": self._missing_payload(bucket["missing"]),
                }
            )
        return result

    def account_history(
        self,
        *,
        book_id: int,
        account_id: int,
        start_date: str,
        end_date: str,
    ) -> dict[str, object]:
        start, end = self._period(start_date, end_date)
        account = self._accounts.get_account(book_id, account_id)
        if account.type not in {"ASSET", "LIABILITY"} or account.currency_code is None:
            raise ReportingError("account history requires an ASSET or LIABILITY account")
        opening = int(
            self._database.connection.execute(
                """
                SELECT COALESCE(SUM(e.quantity_minor), 0)
                FROM entries e
                JOIN transactions t ON t.id = e.transaction_id AND t.book_id = e.book_id
                WHERE e.book_id = ? AND e.account_id = ? AND t.transaction_date < ?
                """,
                (book_id, account_id, start),
            ).fetchone()[0]
        )
        rows = self._database.connection.execute(
            """
            SELECT t.transaction_date, SUM(e.quantity_minor) AS quantity_delta
            FROM entries e
            JOIN transactions t ON t.id = e.transaction_id AND t.book_id = e.book_id
            WHERE e.book_id = ? AND e.account_id = ?
              AND t.transaction_date BETWEEN ? AND ?
            GROUP BY t.transaction_date
            ORDER BY t.transaction_date
            """,
            (book_id, account_id, start, end),
        ).fetchall()
        balance = opening
        points: list[dict[str, object]] = []
        overall_missing: set[tuple[str, str]] = set()
        for row in rows:
            balance += int(row["quantity_delta"] or 0)
            point_date = str(row["transaction_date"])
            point_missing: set[tuple[str, str]] = set()
            base_value = self._convert_amount(
                book_id,
                balance,
                account.currency_code,
                point_date,
                point_missing,
            )
            overall_missing.update(point_missing)
            points.append(
                {
                    "date": point_date,
                    "balanceMinor": balance,
                    "baseValueMinor": base_value,
                    "complete": base_value is not None,
                    "missingFx": self._missing_payload(point_missing),
                }
            )
        ending_missing: set[tuple[str, str]] = set()
        ending_base = self._convert_amount(
            book_id,
            balance,
            account.currency_code,
            end,
            ending_missing,
        )
        overall_missing.update(ending_missing)
        if not points:
            points.append(
                {
                    "date": end,
                    "balanceMinor": balance,
                    "baseValueMinor": ending_base,
                    "complete": ending_base is not None,
                    "missingFx": self._missing_payload(ending_missing),
                }
            )
        return {
            "accountId": account.id,
            "name": account.name,
            "type": account.type,
            "currency": account.currency_code,
            "baseCurrency": self._fx.base_currency(book_id),
            "startDate": start,
            "endDate": end,
            "openingBalanceMinor": opening,
            "endingBalanceMinor": balance,
            "endingBaseValueMinor": ending_base,
            "points": points,
            "complete": not overall_missing,
            "missingFx": self._missing_payload(overall_missing),
        }

    def _balance_overview(self, book_id: int, as_of_date: str) -> dict[str, object]:
        self._fx.base_currency(book_id)
        rows = self._database.connection.execute(
            """
            SELECT a.id, a.name, a.type, a.currency_code,
                   COALESCE((
                       SELECT SUM(e.quantity_minor)
                       FROM entries e
                       JOIN transactions t
                         ON t.id = e.transaction_id AND t.book_id = e.book_id
                       WHERE e.book_id = a.book_id AND e.account_id = a.id
                         AND t.transaction_date <= ?
                   ), 0) AS quantity_balance
            FROM accounts a
            WHERE a.book_id = ? AND a.type IN ('ASSET', 'LIABILITY')
            ORDER BY a.type, a.name COLLATE NOCASE, a.id
            """,
            (as_of_date, book_id),
        ).fetchall()
        missing: set[tuple[str, str]] = set()
        account_items: list[dict[str, object]] = []
        assets = 0
        liabilities = 0
        complete = True
        for row in rows:
            quantity = int(row["quantity_balance"] or 0)
            currency = str(row["currency_code"])
            item_missing: set[tuple[str, str]] = set()
            base_value = self._convert_amount(
                book_id,
                quantity,
                currency,
                as_of_date,
                item_missing,
            )
            missing.update(item_missing)
            if base_value is None:
                complete = False
            elif str(row["type"]) == "ASSET":
                assets += base_value
            else:
                liabilities += base_value
            account_items.append(
                {
                    "accountId": int(row["id"]),
                    "name": str(row["name"]),
                    "type": str(row["type"]),
                    "currency": currency,
                    "balanceMinor": quantity,
                    "baseValueMinor": base_value,
                    "complete": base_value is not None,
                    "missingFx": self._missing_payload(item_missing),
                }
            )
        return {
            "assetsMinor": assets if complete else None,
            "liabilitiesMinor": liabilities if complete else None,
            "netWorthMinor": assets + liabilities if complete else None,
            "complete": complete,
            "accounts": account_items,
            "missingFx": self._missing_payload(missing),
        }

    def _period_totals(self, book_id: int, start_date: str, end_date: str) -> dict[str, object]:
        income = 0
        expense = 0
        income_complete = True
        expense_complete = True
        missing: set[tuple[str, str]] = set()
        for row in self._flow_rows(book_id, start_date, end_date):
            converted = self._convert_row(book_id, row, missing)
            account_type = str(row["account_type"])
            if converted is None:
                if account_type == "INCOME":
                    income_complete = False
                else:
                    expense_complete = False
            elif account_type == "INCOME":
                income -= converted
            else:
                expense += converted
        return {
            "incomeMinor": income if income_complete else None,
            "expenseMinor": expense if expense_complete else None,
            "complete": income_complete and expense_complete,
            "missingFx": self._missing_payload(missing),
        }

    def _flow_rows(
        self,
        book_id: int,
        start_date: str,
        end_date: str,
        *,
        account_type: str | None = None,
    ):
        self._fx.base_currency(book_id)
        params: list[object] = [book_id, start_date, end_date]
        type_clause = ""
        if account_type is not None:
            type_clause = " AND a.type = ?"
            params.append(account_type)
        return self._database.connection.execute(
            f"""
            SELECT e.transaction_id, e.account_id, e.value_minor,
                   a.name AS account_name, a.type AS account_type,
                   t.transaction_date, t.currency_code, t.payee_id,
                   p.name AS payee_name
            FROM entries e
            JOIN accounts a ON a.id = e.account_id AND a.book_id = e.book_id
            JOIN transactions t ON t.id = e.transaction_id AND t.book_id = e.book_id
            LEFT JOIN payees p ON p.id = t.payee_id AND p.book_id = t.book_id
            WHERE e.book_id = ? AND t.transaction_date BETWEEN ? AND ?
              AND a.type IN ('INCOME', 'EXPENSE')
              {type_clause}
            ORDER BY t.transaction_date, t.id, e.id
            """,
            params,
        ).fetchall()

    def _convert_row(
        self,
        book_id: int,
        row,
        missing: set[tuple[str, str]],
    ) -> int | None:
        return self._convert_amount(
            book_id,
            int(row["value_minor"]),
            str(row["currency_code"]),
            str(row["transaction_date"]),
            missing,
        )

    def _convert_amount(
        self,
        book_id: int,
        amount_minor: int,
        currency_code: str,
        rate_date: str,
        missing: set[tuple[str, str]],
    ) -> int | None:
        if amount_minor == 0:
            return 0
        try:
            return self._fx.convert_minor(
                book_id=book_id,
                amount_minor=amount_minor,
                currency_code=currency_code,
                rate_date=rate_date,
            )
        except FxRateMissingError as exc:
            missing.add((exc.currency_code, exc.rate_date))
            return None

    @staticmethod
    def _date(raw: str, name: str) -> str:
        if not isinstance(raw, str):
            raise ReportingError(f"{name} must be YYYY-MM-DD")
        try:
            parsed = date.fromisoformat(raw)
        except ValueError as exc:
            raise ReportingError(f"{name} must be YYYY-MM-DD") from exc
        return parsed.isoformat()

    def _period(self, start_date: str, end_date: str) -> tuple[str, str]:
        start = self._date(start_date, "start_date")
        end = self._date(end_date, "end_date")
        if start > end:
            raise ReportingError("start_date must not be after end_date")
        return start, end

    @staticmethod
    def _validate_limit(limit: int | None) -> None:
        if limit is None:
            return
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ReportingError("report limit must be between 1 and 500")

    @staticmethod
    def _missing_payload(missing) -> list[dict[str, str]]:
        return [
            {"currency": currency, "date": rate_date}
            for currency, rate_date in sorted(missing)
        ]

    @classmethod
    def _merge_missing(cls, *groups) -> list[dict[str, str]]:
        merged = {
            (str(item["currency"]), str(item["date"]))
            for group in groups
            for item in group
        }
        return cls._missing_payload(merged)
