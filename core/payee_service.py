from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import dataclass

from core.database import Database
from core.errors import (
    CrossBookReferenceError,
    PayeeArchivedError,
    PayeeCollisionError,
    PayeeNotFoundError,
    ValidationError,
)

_SPACE_RE = re.compile(r"\s+")
_ALIAS_MATCH_TYPES = {"EXACT", "PREFIX"}


def normalize_payee_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError("payee text must be a string")
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    normalized = _SPACE_RE.sub(" ", normalized)
    if not normalized:
        raise ValidationError("payee text cannot be empty")
    return normalized


@dataclass(frozen=True, slots=True)
class Payee:
    id: int
    book_id: int
    name: str
    normalized_name: str
    archived: bool


@dataclass(frozen=True, slots=True)
class PayeeSuggestion:
    id: int
    name: str
    usage_count: int
    last_used: str | None
    matched_by: str


class PayeeService:
    def __init__(self, database: Database) -> None:
        self._database = database

    def create_payee(self, *, book_id: int, name: str) -> Payee:
        clean_name = name.strip()
        normalized = normalize_payee_text(clean_name)
        self._ensure_book_exists(book_id)
        with self._database.transaction() as conn:
            self._ensure_namespace_available(conn, book_id, normalized)
            cursor = conn.execute(
                """
                INSERT INTO payees(book_id, name, normalized_name, created_at, updated_at)
                VALUES (?, ?, ?, datetime('now'), datetime('now'))
                """,
                (book_id, clean_name, normalized),
            )
            payee_id = int(cursor.lastrowid)
        return self.get_payee(book_id, payee_id)

    def get_payee(self, book_id: int, payee_id: int) -> Payee:
        row = self._database.connection.execute(
            "SELECT id, book_id, name, normalized_name, archived FROM payees WHERE id = ? AND book_id = ?",
            (payee_id, book_id),
        ).fetchone()
        if row is None:
            other = self._database.connection.execute(
                "SELECT book_id FROM payees WHERE id = ?", (payee_id,)
            ).fetchone()
            if other is not None:
                raise CrossBookReferenceError(f"payee {payee_id} belongs to another book")
            raise PayeeNotFoundError(f"unknown payee id: {payee_id}")
        return self._row_to_payee(row)

    def rename_payee(self, book_id: int, payee_id: int, name: str) -> Payee:
        payee = self.get_payee(book_id, payee_id)
        if payee.archived:
            raise PayeeArchivedError("archived payees cannot be renamed")
        clean_name = name.strip()
        normalized = normalize_payee_text(clean_name)
        if normalized == payee.normalized_name:
            with self._database.transaction() as conn:
                conn.execute(
                    "UPDATE payees SET name = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                    (clean_name, payee_id, book_id),
                )
            return self.get_payee(book_id, payee_id)
        with self._database.transaction() as conn:
            self._ensure_namespace_available(conn, book_id, normalized, ignore_payee_id=payee_id)
            conn.execute(
                "UPDATE payees SET name = ?, normalized_name = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (clean_name, normalized, payee_id, book_id),
            )
        return self.get_payee(book_id, payee_id)

    def set_archived(self, book_id: int, payee_id: int, archived: bool) -> Payee:
        self.get_payee(book_id, payee_id)
        with self._database.transaction() as conn:
            conn.execute(
                "UPDATE payees SET archived = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (int(archived), payee_id, book_id),
            )
        return self.get_payee(book_id, payee_id)

    def add_alias(
        self,
        *,
        book_id: int,
        payee_id: int,
        alias: str,
        match_type: str = "EXACT",
    ) -> int:
        payee = self.get_payee(book_id, payee_id)
        if payee.archived:
            raise PayeeArchivedError("cannot add aliases to an archived payee")
        match_type = match_type.upper()
        if match_type not in _ALIAS_MATCH_TYPES:
            raise ValidationError(f"unsupported alias match type: {match_type}")
        clean_alias = alias.strip()
        normalized = normalize_payee_text(clean_alias)
        if normalized == payee.normalized_name:
            raise PayeeCollisionError("alias duplicates the canonical payee name")
        with self._database.transaction() as conn:
            self._ensure_namespace_available(conn, book_id, normalized, ignore_payee_id=payee_id)
            existing = conn.execute(
                "SELECT id FROM payee_aliases WHERE book_id = ? AND payee_id = ? AND normalized_alias = ?",
                (book_id, payee_id, normalized),
            ).fetchone()
            if existing is not None:
                raise PayeeCollisionError("alias already exists for this payee")
            cursor = conn.execute(
                """
                INSERT INTO payee_aliases(payee_id, book_id, alias, normalized_alias, match_type, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (payee_id, book_id, clean_alias, normalized, match_type),
            )
            return int(cursor.lastrowid)

    def remove_alias(self, book_id: int, payee_id: int, alias_id: int) -> None:
        self.get_payee(book_id, payee_id)
        with self._database.transaction() as conn:
            cursor = conn.execute(
                "DELETE FROM payee_aliases WHERE id = ? AND payee_id = ? AND book_id = ?",
                (alias_id, payee_id, book_id),
            )
            if cursor.rowcount != 1:
                raise PayeeNotFoundError(f"unknown alias id: {alias_id}")

    def assign_transaction(
        self,
        *,
        book_id: int,
        transaction_id: int,
        payee_id: int | None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        conn = connection or self._database.connection
        owns_transaction = connection is None
        try:
            transaction = conn.execute(
                "SELECT book_id FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
            if transaction is None:
                raise ValidationError(f"unknown transaction id: {transaction_id}")
            if int(transaction["book_id"]) != book_id:
                raise CrossBookReferenceError("transaction belongs to another book")
            if payee_id is not None:
                row = conn.execute(
                    "SELECT book_id, archived FROM payees WHERE id = ?", (payee_id,)
                ).fetchone()
                if row is None:
                    raise PayeeNotFoundError(f"unknown payee id: {payee_id}")
                if int(row["book_id"]) != book_id:
                    raise CrossBookReferenceError("payee belongs to another book")
                if bool(row["archived"]):
                    raise PayeeArchivedError("archived payee cannot be assigned")
            conn.execute(
                "UPDATE transactions SET payee_id = ?, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (payee_id, transaction_id, book_id),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction:
                conn.rollback()
            raise

    def merge_payees(self, *, book_id: int, source_id: int, target_id: int) -> Payee:
        if source_id == target_id:
            raise ValidationError("source and target payees must differ")
        source = self.get_payee(book_id, source_id)
        target = self.get_payee(book_id, target_id)
        if source.archived or target.archived:
            raise PayeeArchivedError("only active payees can be merged")

        with self._database.transaction() as conn:
            aliases = conn.execute(
                "SELECT alias, normalized_alias, match_type FROM payee_aliases WHERE payee_id = ? AND book_id = ?",
                (source_id, book_id),
            ).fetchall()
            candidates = [(source.name, source.normalized_name, "EXACT")]
            candidates.extend(
                (str(row["alias"]), str(row["normalized_alias"]), str(row["match_type"]))
                for row in aliases
            )
            for _, normalized, _ in candidates:
                if normalized == target.normalized_name:
                    continue
                self._ensure_namespace_available(
                    conn,
                    book_id,
                    normalized,
                    ignore_payee_id=source_id,
                    allow_payee_id=target_id,
                )

            conn.execute(
                "UPDATE transactions SET payee_id = ? WHERE book_id = ? AND payee_id = ?",
                (target_id, book_id, source_id),
            )
            conn.execute(
                "DELETE FROM payee_aliases WHERE book_id = ? AND payee_id = ?",
                (book_id, source_id),
            )
            for alias, normalized, match_type in candidates:
                if normalized == target.normalized_name:
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM payee_aliases WHERE book_id = ? AND payee_id = ? AND normalized_alias = ?",
                    (book_id, target_id, normalized),
                ).fetchone()
                if exists is None:
                    conn.execute(
                        """
                        INSERT INTO payee_aliases(payee_id, book_id, alias, normalized_alias, match_type, created_at)
                        VALUES (?, ?, ?, ?, ?, datetime('now'))
                        """,
                        (target_id, book_id, alias, normalized, match_type),
                    )
            conn.execute(
                "UPDATE payees SET archived = 1, updated_at = datetime('now') WHERE id = ? AND book_id = ?",
                (source_id, book_id),
            )
        return self.get_payee(book_id, target_id)

    def suggest_payees(self, book_id: int, query: str = "", *, limit: int = 5) -> list[PayeeSuggestion]:
        if limit < 1 or limit > 50:
            raise ValidationError("suggestion limit must be between 1 and 50")
        normalized_query = "" if not query.strip() else normalize_payee_text(query)
        rows = self._database.connection.execute(
            """
            SELECT p.id, p.name, p.normalized_name,
                   COUNT(t.id) AS usage_count,
                   MAX(t.transaction_date || COALESCE('T' || t.transaction_time, '')) AS last_used
            FROM payees p
            LEFT JOIN transactions t ON t.book_id = p.book_id AND t.payee_id = p.id
            WHERE p.book_id = ? AND p.archived = 0
            GROUP BY p.id
            """,
            (book_id,),
        ).fetchall()
        aliases = self._database.connection.execute(
            "SELECT payee_id, normalized_alias FROM payee_aliases WHERE book_id = ?",
            (book_id,),
        ).fetchall()
        alias_map: dict[int, list[str]] = {}
        for row in aliases:
            alias_map.setdefault(int(row["payee_id"]), []).append(str(row["normalized_alias"]))

        ranked: list[tuple[tuple[object, ...], PayeeSuggestion]] = []
        for row in rows:
            payee_id = int(row["id"])
            name_norm = str(row["normalized_name"])
            payee_aliases = alias_map.get(payee_id, [])
            if not normalized_query:
                relevance = 4
                matched_by = "usage"
            elif name_norm == normalized_query:
                relevance = 0
                matched_by = "name_exact"
            elif name_norm.startswith(normalized_query):
                relevance = 1
                matched_by = "name_prefix"
            elif any(alias == normalized_query for alias in payee_aliases):
                relevance = 2
                matched_by = "alias_exact"
            elif any(alias.startswith(normalized_query) for alias in payee_aliases):
                relevance = 3
                matched_by = "alias_prefix"
            else:
                continue
            usage = int(row["usage_count"])
            last_used = None if row["last_used"] is None else str(row["last_used"])
            suggestion = PayeeSuggestion(payee_id, str(row["name"]), usage, last_used, matched_by)
            ranked.append(((relevance, -usage, "" if last_used is None else "~" + last_used, name_norm, payee_id), suggestion))

        ranked.sort(key=lambda item: item[0])
        # last_used is handled explicitly after relevance/usage so newer ISO timestamps win.
        grouped: list[PayeeSuggestion] = []
        for relevance in sorted({item[0][0] for item in ranked}):
            group = [item[1] for item in ranked if item[0][0] == relevance]
            group.sort(key=lambda item: (item.name.casefold(), item.id))
            group.sort(key=lambda item: item.last_used or "", reverse=True)
            group.sort(key=lambda item: item.usage_count, reverse=True)
            grouped.extend(group)
        return grouped[:limit]

    def aliases_for(self, book_id: int, payee_id: int) -> list[tuple[int, str, str]]:
        self.get_payee(book_id, payee_id)
        rows = self._database.connection.execute(
            "SELECT id, alias, match_type FROM payee_aliases WHERE book_id = ? AND payee_id = ? ORDER BY normalized_alias",
            (book_id, payee_id),
        ).fetchall()
        return [(int(row["id"]), str(row["alias"]), str(row["match_type"])) for row in rows]

    def _ensure_namespace_available(
        self,
        conn: sqlite3.Connection,
        book_id: int,
        normalized: str,
        *,
        ignore_payee_id: int | None = None,
        allow_payee_id: int | None = None,
    ) -> None:
        canonical = conn.execute(
            "SELECT id FROM payees WHERE book_id = ? AND normalized_name = ?",
            (book_id, normalized),
        ).fetchone()
        if canonical is not None:
            owner = int(canonical["id"])
            if owner not in {ignore_payee_id, allow_payee_id}:
                raise PayeeCollisionError("payee name collides with an existing canonical name")
        alias = conn.execute(
            "SELECT payee_id FROM payee_aliases WHERE book_id = ? AND normalized_alias = ?",
            (book_id, normalized),
        ).fetchone()
        if alias is not None:
            owner = int(alias["payee_id"])
            if owner not in {ignore_payee_id, allow_payee_id}:
                raise PayeeCollisionError("payee text collides with an existing alias")

    def _ensure_book_exists(self, book_id: int) -> None:
        row = self._database.connection.execute(
            "SELECT 1 FROM books WHERE id = ? AND archived = 0", (book_id,)
        ).fetchone()
        if row is None:
            raise ValidationError(f"book does not exist or is archived: {book_id}")

    @staticmethod
    def _row_to_payee(row: sqlite3.Row) -> Payee:
        return Payee(
            id=int(row["id"]),
            book_id=int(row["book_id"]),
            name=str(row["name"]),
            normalized_name=str(row["normalized_name"]),
            archived=bool(row["archived"]),
        )
