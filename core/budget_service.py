from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from core.account_service import AccountService
from core.category_service import CategoryService
from core.database import Database
from core.errors import BudgetError
from core.fx_service import FxService
from core.reporting_service import ReportingService


@dataclass(frozen=True, slots=True)
class Budget:
    id: int
    book_id: int
    category_account_id: int
    period: str
    amount_minor: int


class BudgetService:
    """Own monthly expense budgets and compare them with canonical ledger reporting."""

    def __init__(
        self,
        database: Database,
        reporting: ReportingService,
        fx: FxService,
        accounts: AccountService,
        categories: CategoryService,
    ) -> None:
        self._database = database
        self._reporting = reporting
        self._fx = fx
        self._accounts = accounts
        self._categories = categories

    def set_budget(
        self,
        *,
        book_id: int,
        category_account_id: int,
        period: str,
        amount_minor: int,
    ) -> Budget:
        normalized_period = self._period(period)
        if (
            isinstance(amount_minor, bool)
            or not isinstance(amount_minor, int)
            or amount_minor <= 0
        ):
            raise BudgetError("budget amount_minor must be a positive integer")
        category = self._accounts.get_account(book_id, category_account_id)
        if category.type != "EXPENSE":
            raise BudgetError("budgets require an EXPENSE category")
        if category.archived:
            raise BudgetError("budgets require a non-archived category")
        self._assert_no_overlap(book_id, normalized_period, category_account_id)

        with self._database.transaction() as conn:
            conn.execute(
                """
                INSERT INTO budgets(
                    book_id, category_account_id, period, amount_minor, created_at, updated_at
                ) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(book_id, category_account_id, period) DO UPDATE SET
                    amount_minor=excluded.amount_minor,
                    updated_at=datetime('now')
                """,
                (book_id, category_account_id, normalized_period, amount_minor),
            )
        return self.get_budget(book_id, category_account_id, normalized_period)

    def get_budget(self, book_id: int, category_account_id: int, period: str) -> Budget:
        normalized_period = self._period(period)
        row = self._database.connection.execute(
            """
            SELECT id, book_id, category_account_id, period, amount_minor
            FROM budgets
            WHERE book_id=? AND category_account_id=? AND period=?
            """,
            (book_id, category_account_id, normalized_period),
        ).fetchone()
        if row is None:
            raise BudgetError("budget not found")
        return self._record(row)

    def delete_budget(self, *, book_id: int, budget_id: int) -> None:
        if isinstance(budget_id, bool) or not isinstance(budget_id, int) or budget_id < 1:
            raise BudgetError("invalid budget identifier")
        with self._database.transaction() as conn:
            deleted = conn.execute(
                "DELETE FROM budgets WHERE id=? AND book_id=?",
                (budget_id, book_id),
            ).rowcount
        if deleted != 1:
            raise BudgetError("budget not found")

    def period_status(self, *, book_id: int, period: str) -> dict[str, object]:
        normalized_period = self._period(period)
        start, end = self._period_bounds(normalized_period)
        rows = self._database.connection.execute(
            """
            SELECT id, book_id, category_account_id, period, amount_minor
            FROM budgets
            WHERE book_id=? AND period=?
            ORDER BY category_account_id, id
            """,
            (book_id, normalized_period),
        ).fetchall()
        budgets = [self._record(row) for row in rows]
        base_currency = self._fx.base_currency(book_id)
        children = self._expense_children(book_id)
        self._assert_scopes_non_overlapping(budgets, children)
        targets = self._budget_targets(book_id, budgets, children)
        if not budgets:
            return {
                "period": normalized_period,
                "startDate": start,
                "endDate": end,
                "baseCurrency": base_currency,
                "targets": targets,
                "budgets": [],
                "totalBudgetMinor": 0,
                "totalSpentMinor": 0,
                "totalRemainingMinor": 0,
                "complete": True,
                "missingFx": [],
            }

        report = self._reporting.category_report(
            book_id=book_id,
            start_date=start,
            end_date=end,
            category_type="EXPENSE",
            limit=None,
        )
        direct = {int(item["accountId"]): item for item in report}

        items: list[dict[str, object]] = []
        overall_missing: set[tuple[str, str]] = set()
        total_budget = 0
        total_spent = 0
        total_complete = True
        for budget in budgets:
            subtree = self._subtree_ids(budget.category_account_id, children)
            spent = 0
            complete = True
            missing: set[tuple[str, str]] = set()
            for account_id in subtree:
                item = direct.get(account_id)
                if item is None:
                    continue
                for missing_item in item["missingFx"]:
                    missing.add(
                        (str(missing_item["currency"]), str(missing_item["date"]))
                    )
                if not bool(item["complete"]) or item["amountMinor"] is None:
                    complete = False
                else:
                    spent += int(item["amountMinor"])

            category = self._accounts.get_account(book_id, budget.category_account_id)
            remaining = budget.amount_minor - spent if complete else None
            usage_bps = None
            if complete:
                usage_bps = int(
                    (
                        Decimal(spent)
                        * Decimal(10_000)
                        / Decimal(budget.amount_minor)
                    ).quantize(Decimal(1), rounding=ROUND_HALF_UP)
                )
            overall_missing.update(missing)
            total_budget += budget.amount_minor
            if complete:
                total_spent += spent
            else:
                total_complete = False
            items.append(
                {
                    "id": budget.id,
                    "categoryAccountId": budget.category_account_id,
                    "categoryName": category.name,
                    "categoryPath": self._categories.category_path(
                        book_id, budget.category_account_id
                    ),
                    "amountMinor": budget.amount_minor,
                    "spentMinor": spent if complete else None,
                    "remainingMinor": remaining,
                    "usageBps": usage_bps,
                    "overBudget": None if remaining is None else remaining < 0,
                    "complete": complete,
                    "missingFx": self._missing_payload(missing),
                }
            )

        items.sort(
            key=lambda item: (str(item["categoryPath"]).casefold(), int(item["id"]))
        )
        return {
            "period": normalized_period,
            "startDate": start,
            "endDate": end,
            "baseCurrency": base_currency,
            "targets": targets,
            "budgets": items,
            "totalBudgetMinor": total_budget,
            "totalSpentMinor": total_spent if total_complete else None,
            "totalRemainingMinor": total_budget - total_spent if total_complete else None,
            "complete": total_complete,
            "missingFx": self._missing_payload(overall_missing),
        }

    def _assert_no_overlap(
        self, book_id: int, period: str, category_account_id: int
    ) -> None:
        rows = self._database.connection.execute(
            "SELECT category_account_id FROM budgets WHERE book_id=? AND period=?",
            (book_id, period),
        ).fetchall()
        existing = {int(row["category_account_id"]) for row in rows}
        existing.discard(category_account_id)
        if not existing:
            return
        children = self._expense_children(book_id)
        new_subtree = self._subtree_ids(category_account_id, children)
        for existing_id in existing:
            existing_subtree = self._subtree_ids(existing_id, children)
            if existing_id in new_subtree or category_account_id in existing_subtree:
                raise BudgetError(
                    "budgets in the same period cannot overlap ancestor and descendant categories"
                )

    def _budget_targets(
        self,
        book_id: int,
        budgets: list[Budget],
        children: dict[int, list[int]],
    ) -> list[dict[str, object]]:
        existing = {budget.category_account_id for budget in budgets}
        existing_subtrees = {
            root_id: self._subtree_ids(root_id, children) for root_id in existing
        }
        targets: list[dict[str, object]] = []
        for account in self._accounts.list_accounts(book_id, include_archived=False):
            if account.type != "EXPENSE":
                continue
            candidate_subtree = self._subtree_ids(account.id, children)
            eligible = account.id in existing or all(
                root_id not in candidate_subtree and account.id not in root_subtree
                for root_id, root_subtree in existing_subtrees.items()
            )
            if not eligible:
                continue
            targets.append(
                {
                    "categoryAccountId": account.id,
                    "categoryName": account.name,
                    "categoryPath": self._categories.category_path(book_id, account.id),
                    "placeholder": account.placeholder,
                    "hasBudget": account.id in existing,
                }
            )
        targets.sort(
            key=lambda item: (
                str(item["categoryPath"]).casefold(),
                int(item["categoryAccountId"]),
            )
        )
        return targets

    def _expense_children(self, book_id: int) -> dict[int, list[int]]:
        children: dict[int, list[int]] = {}
        for account in self._accounts.list_accounts(book_id, include_archived=True):
            if account.type != "EXPENSE" or account.parent_id is None:
                continue
            children.setdefault(account.parent_id, []).append(account.id)
        return children

    @classmethod
    def _assert_scopes_non_overlapping(
        cls,
        budgets: list[Budget],
        children: dict[int, list[int]],
    ) -> None:
        subtrees = {
            budget.category_account_id: cls._subtree_ids(
                budget.category_account_id, children
            )
            for budget in budgets
        }
        roots = list(subtrees)
        for index, left in enumerate(roots):
            for right in roots[index + 1 :]:
                if left in subtrees[right] or right in subtrees[left]:
                    raise BudgetError(
                        "existing budgets overlap under the current category hierarchy"
                    )

    @staticmethod
    def _period(value: str) -> str:
        if not isinstance(value, str):
            raise BudgetError("period must use YYYY-MM")
        raw = value.strip()
        if len(raw) != 7 or raw[4] != "-":
            raise BudgetError("period must use YYYY-MM")
        try:
            year = int(raw[:4])
            month = int(raw[5:7])
            date(year, month, 1)
        except ValueError as exc:
            raise BudgetError("period must use YYYY-MM") from exc
        if year < 1:
            raise BudgetError("period must use YYYY-MM")
        return f"{year:04d}-{month:02d}"

    @staticmethod
    def _period_bounds(period: str) -> tuple[str, str]:
        year = int(period[:4])
        month = int(period[5:7])
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1).isoformat(), date(year, month, last_day).isoformat()

    @staticmethod
    def _subtree_ids(root_id: int, children: dict[int, list[int]]) -> set[int]:
        result: set[int] = set()
        stack = [root_id]
        while stack:
            current = stack.pop()
            if current in result:
                raise BudgetError("category hierarchy contains a cycle")
            result.add(current)
            stack.extend(children.get(current, ()))
        return result

    @staticmethod
    def _missing_payload(items: set[tuple[str, str]]) -> list[dict[str, str]]:
        return [
            {"currency": currency, "date": rate_date}
            for currency, rate_date in sorted(items)
        ]

    @staticmethod
    def _record(row) -> Budget:
        return Budget(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            category_account_id=int(row["category_account_id"]),
            period=str(row["period"]),
            amount_minor=int(row["amount_minor"]),
        )
