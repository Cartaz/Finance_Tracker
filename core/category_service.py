from __future__ import annotations

from dataclasses import dataclass

from core.account_service import Account, AccountService
from core.database import Database
from core.errors import CategoryError, ValidationError
from core.payee_service import normalize_payee_text

_CATEGORY_TYPES = {"EXPENSE", "INCOME"}


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    id: int
    name: str
    path: str
    type: str
    payee_usage_count: int
    usage_count: int
    last_used: str | None


class CategoryService:
    def __init__(self, database: Database, accounts: AccountService | None = None) -> None:
        self._database = database
        self._accounts = accounts or AccountService(database)

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
            raise CategoryError("categories must be EXPENSE or INCOME accounts")
        self._ensure_sibling_name_available(
            book_id,
            category_type,
            parent_id,
            name,
        )
        return self._accounts.create_account(
            book_id=book_id,
            account_type=category_type,
            name=name,
            parent_id=parent_id,
            placeholder=placeholder,
        )

    def rename_category(self, book_id: int, category_id: int, name: str) -> Account:
        category = self._require_category(book_id, category_id)
        self._ensure_sibling_name_available(
            book_id,
            category.type,
            category.parent_id,
            name,
            ignore_category_id=category_id,
        )
        return self._accounts.rename_account(book_id, category_id, name)

    def move_category(
        self,
        book_id: int,
        category_id: int,
        new_parent_id: int | None,
    ) -> Account:
        category = self._require_category(book_id, category_id)
        if new_parent_id is not None:
            parent = self._require_category(book_id, new_parent_id)
            if parent.type != category.type:
                raise CategoryError("parent and child category types must match")
        self._ensure_sibling_name_available(
            book_id,
            category.type,
            new_parent_id,
            category.name,
            ignore_category_id=category_id,
        )
        return self._accounts.move_account(book_id, category_id, new_parent_id)

    def set_archived(self, book_id: int, category_id: int, archived: bool) -> Account:
        self._require_category(book_id, category_id)
        return self._accounts.set_archived(book_id, category_id, archived)

    def category_path(self, book_id: int, category_id: int) -> str:
        category = self._require_category(book_id, category_id)
        names = [category.name]
        current = category
        seen = {category.id}
        while current.parent_id is not None:
            if current.parent_id in seen:
                raise CategoryError("category hierarchy contains a cycle")
            seen.add(current.parent_id)
            current = self._accounts.get_account(book_id, current.parent_id)
            names.append(current.name)
        return " › ".join(reversed(names))

    def suggest_categories(
        self,
        book_id: int,
        query: str = "",
        *,
        category_type: str = "EXPENSE",
        payee_id: int | None = None,
        limit: int = 5,
    ) -> list[CategorySuggestion]:
        category_type = category_type.upper()
        if category_type not in _CATEGORY_TYPES:
            raise CategoryError("category_type must be EXPENSE or INCOME")
        if limit < 1 or limit > 50:
            raise ValidationError("suggestion limit must be between 1 and 50")
        normalized_query = "" if not query.strip() else normalize_payee_text(query)

        if payee_id is not None:
            payee = self._database.connection.execute(
                "SELECT book_id, archived FROM payees WHERE id = ?",
                (payee_id,),
            ).fetchone()
            if (
                payee is None
                or int(payee["book_id"]) != book_id
                or bool(payee["archived"])
            ):
                raise CategoryError("payee is unavailable in this book")

        rows = self._database.connection.execute(
            """
            SELECT a.id, a.name, a.type,
                   COUNT(e.id) AS usage_count,
                   MAX(t.transaction_date || COALESCE('T' || t.transaction_time, '')) AS last_used,
                   SUM(CASE WHEN ? IS NOT NULL AND t.payee_id = ? THEN 1 ELSE 0 END)
                       AS payee_usage_count
            FROM accounts a
            LEFT JOIN entries e
                ON e.book_id = a.book_id AND e.account_id = a.id
            LEFT JOIN transactions t
                ON t.book_id = e.book_id AND t.id = e.transaction_id
            WHERE a.book_id = ? AND a.type = ?
              AND a.archived = 0 AND a.placeholder = 0
            GROUP BY a.id
            """,
            (payee_id, payee_id, book_id, category_type),
        ).fetchall()

        suggestions: list[CategorySuggestion] = []
        for row in rows:
            category_id = int(row["id"])
            path = self.category_path(book_id, category_id)
            name_norm = normalize_payee_text(str(row["name"]))
            path_norm = normalize_payee_text(path.replace("›", " "))
            if normalized_query and not (
                name_norm.startswith(normalized_query)
                or path_norm.startswith(normalized_query)
                or f" {normalized_query}" in path_norm
            ):
                continue
            suggestions.append(
                CategorySuggestion(
                    id=category_id,
                    name=str(row["name"]),
                    path=path,
                    type=str(row["type"]),
                    payee_usage_count=int(row["payee_usage_count"] or 0),
                    usage_count=int(row["usage_count"] or 0),
                    last_used=(
                        None if row["last_used"] is None else str(row["last_used"])
                    ),
                )
            )

        suggestions.sort(key=lambda item: (item.path.casefold(), item.id))
        suggestions.sort(key=lambda item: item.last_used or "", reverse=True)
        suggestions.sort(key=lambda item: item.usage_count, reverse=True)
        if payee_id is not None:
            suggestions.sort(key=lambda item: item.payee_usage_count, reverse=True)
        return suggestions[:limit]

    def _require_category(self, book_id: int, category_id: int) -> Account:
        account = self._accounts.get_account(book_id, category_id)
        if account.type not in _CATEGORY_TYPES:
            raise CategoryError(f"account {category_id} is not a category")
        return account

    def _ensure_sibling_name_available(
        self,
        book_id: int,
        category_type: str,
        parent_id: int | None,
        name: str,
        *,
        ignore_category_id: int | None = None,
    ) -> None:
        normalized = normalize_payee_text(name)
        for account in self._accounts.list_accounts(book_id, include_archived=True):
            if account.id == ignore_category_id:
                continue
            if account.type != category_type or account.parent_id != parent_id:
                continue
            if normalize_payee_text(account.name) == normalized:
                raise CategoryError("a sibling category with this name already exists")
