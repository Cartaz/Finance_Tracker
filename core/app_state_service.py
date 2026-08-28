from __future__ import annotations

from core.account_service import Account, AccountService
from core.currency_registry import CurrencyRegistry
from core.database import Database
from core.posting_policy import PostingPolicy


class AppStateService:
    """Build presentation-ready read models without leaking queries into orchestration."""

    def __init__(self, database: Database, accounts: AccountService) -> None:
        self._database = database
        self._accounts = accounts
        self._currencies = CurrencyRegistry(database.connection)

    def snapshot(
        self,
        *,
        book_id: int,
        book_name: str,
        book_currency: str,
    ) -> dict[str, object]:
        accounts = self._accounts.list_accounts(book_id)
        visible_accounts = [account for account in accounts if account.type != "EQUITY"]
        transactions = self._database.connection.execute(
            """
            SELECT t.id, t.kind, t.transaction_date, t.transaction_time, t.currency_code,
                   t.description, p.name AS payee_name
            FROM transactions t LEFT JOIN payees p ON p.id = t.payee_id
            WHERE t.book_id = ?
            ORDER BY t.transaction_date DESC, COALESCE(t.transaction_time, '') DESC, t.id DESC
            LIMIT 100
            """,
            (book_id,),
        ).fetchall()
        return {
            "book": {"id": book_id, "name": book_name, "currency": book_currency},
            "accounts": [
                self._account_payload(book_id, item, accounts) for item in visible_accounts
            ],
            "transactions": [dict(row) for row in transactions],
        }

    def supported_currencies(self) -> list[dict[str, object]]:
        return [
            {"code": item.code, "minorUnitDigits": item.minor_unit_digits}
            for item in self._currencies.list_active()
        ]

    def _account_payload(
        self,
        book_id: int,
        account: Account,
        accounts: list[Account],
    ) -> dict[str, object]:
        capabilities: dict[str, list[int]] = {}
        if (
            account.type in {"ASSET", "LIABILITY"}
            and account.currency_code is not None
            and not account.archived
            and not account.placeholder
        ):
            for kind in ("EXPENSE", "INCOME", "REFUND", "TRANSFER"):
                capabilities[kind] = [
                    candidate.id
                    for candidate in accounts
                    if PostingPolicy.counter_is_eligible(
                        kind,
                        source_account_id=account.id,
                        source_currency=account.currency_code,
                        counter_account_id=candidate.id,
                        counter_type=candidate.type,
                        counter_currency=candidate.currency_code,
                        counter_archived=candidate.archived,
                        counter_placeholder=candidate.placeholder,
                    )
                ]
        return {
            "id": account.id,
            "parentId": account.parent_id,
            "name": account.name,
            "type": account.type,
            "currency": account.currency_code,
            "placeholder": account.placeholder,
            "archived": account.archived,
            "balanceMinor": self._accounts.native_balance(book_id, account.id)
            if account.type in {"ASSET", "LIABILITY"}
            else None,
            "postingCapabilities": capabilities,
        }
