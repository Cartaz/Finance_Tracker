from __future__ import annotations

import csv
import hashlib
import io
import re
import sqlite3
import unicodedata
from datetime import date, datetime

from core.account_service import AccountService
from core.database import Database
from core.errors import ReconciliationAmbiguousError, ReconciliationError
from core.ledger_service import LedgerService
from core.money import parse_money
from core.payee_service import PayeeService
from core.posting_policy import PostingPolicy
from core.tracking_policy import TrackingBoundaryPolicy, TrackingBoundaryStatus

_REVIEW_MODES = {"FULL_REVIEW", "ASSISTED_REVIEW"}
_TERMINAL_STATES = {"MATCHED", "POSTED", "IGNORED"}
_BLOCKED_POST_STATES = {"OUTSIDE_TRACKING", "TRACKING_AMBIGUOUS"}
_HEADER_RE = re.compile(r"[^a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")
_DATE_HEADERS = ("date", "bookingdate", "transactiondate", "data", "valuedate")
_AMOUNT_HEADERS = ("amount", "transactionamount", "importo", "value", "ammontare")
_CURRENCY_HEADERS = ("currency", "currencycode", "valuta", "ccy")
_DESCRIPTION_HEADERS = (
    "description", "descrizione", "details", "causale", "memo", "narrative"
)
_EXTERNAL_ID_HEADERS = (
    "externalid", "transactionid", "bankid", "reference", "riferimento", "id"
)


class ReconciliationService:
    """Stage external bank evidence without becoming a second ledger writer.

    Imported rows are proposals. Heuristic candidates never become MATCHED
    automatically; only a previously persisted external bank identity can do so.
    Posting always delegates to LedgerService inside the same database transaction.
    """

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

    def import_csv(
        self,
        *,
        book_id: int,
        account_id: int,
        source_name: str,
        csv_text: str,
        review_mode: str,
    ) -> dict[str, object]:
        account = self._accounts.get_account(book_id, account_id)
        if account.type not in {"ASSET", "LIABILITY"} or account.currency_code is None:
            raise ReconciliationError("imports require a balance account")
        if account.archived or account.placeholder:
            raise ReconciliationError("imports require an active non-placeholder account")

        source = self._normalize_source(source_name)
        if not isinstance(review_mode, str):
            raise ReconciliationError("review_mode must be FULL_REVIEW or ASSISTED_REVIEW")
        mode = review_mode.strip().upper()
        if mode not in _REVIEW_MODES:
            raise ReconciliationError("review_mode must be FULL_REVIEW or ASSISTED_REVIEW")
        if not isinstance(csv_text, str) or not csv_text.strip():
            raise ReconciliationError("CSV content is empty")
        if len(csv_text.encode("utf-8")) > 10_000_000:
            raise ReconciliationError("CSV content exceeds 10 MB")

        raw_rows = self._parse_csv(csv_text)
        if not raw_rows:
            raise ReconciliationError("CSV contains no data rows")
        if len(raw_rows) > 10_000:
            raise ReconciliationError("CSV import is limited to 10000 rows")

        prepared: list[dict[str, object]] = []
        seen_external: set[str] = set()
        for row_number, raw in enumerate(raw_rows, start=2):
            transaction_date = self._parse_date(raw["date"], row_number)
            currency = (raw.get("currency") or account.currency_code).strip().upper()
            if currency != account.currency_code:
                raise ReconciliationError(
                    f"row {row_number}: booked currency {currency} does not match "
                    f"account currency {account.currency_code}"
                )
            amount_minor = parse_money(raw["amount"], self._database.currency(currency))
            if amount_minor == 0:
                raise ReconciliationError(f"row {row_number}: zero amount is not importable")
            description = (raw.get("description") or "").strip()
            external_id = (raw.get("external_id") or "").strip() or None
            if external_id is not None:
                if external_id in seen_external:
                    raise ReconciliationAmbiguousError(
                        f"duplicate external id inside CSV: {external_id}"
                    )
                seen_external.add(external_id)
            prepared.append(
                {
                    "row_number": row_number,
                    "date": transaction_date,
                    "amount_minor": amount_minor,
                    "currency": currency,
                    "description": description,
                    "external_id": external_id,
                    "fingerprint": self._fingerprint(
                        account_id, transaction_date, amount_minor, currency, description
                    ),
                }
            )

        with self._database.transaction() as conn:
            batch_id = int(
                conn.execute(
                    """
                    INSERT INTO import_batches(
                        book_id, account_id, source_name, review_mode, imported_at, row_count
                    ) VALUES (?, ?, ?, ?, datetime('now'), ?)
                    """,
                    (book_id, account_id, source, mode, len(prepared)),
                ).lastrowid
            )
            summary: dict[str, int] = {}
            for item in prepared:
                state, matched_transaction_id = self._initial_state(
                    book_id=book_id,
                    account_id=account_id,
                    source_name=source,
                    external_id=item["external_id"],
                    fingerprint=str(item["fingerprint"]),
                    transaction_date=str(item["date"]),
                    amount_minor=int(item["amount_minor"]),
                    review_mode=mode,
                    tracking_start_date=account.tracking_start_date,
                    tracking_start_time=account.tracking_start_time,
                )
                conn.execute(
                    """
                    INSERT INTO import_rows(
                        batch_id, book_id, row_number, transaction_date, amount_minor,
                        currency_code, description, external_id, fingerprint, review_state,
                        matched_transaction_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (
                        batch_id, book_id, item["row_number"], item["date"],
                        item["amount_minor"], item["currency"], item["description"],
                        item["external_id"], item["fingerprint"], state,
                        matched_transaction_id,
                    ),
                )
                summary[state] = summary.get(state, 0) + 1
        return {"batchId": batch_id, "rowCount": len(prepared), "summary": summary}

    def list_batches(self, book_id: int, *, limit: int = 50) -> list[dict[str, object]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ReconciliationError("batch limit must be between 1 and 200")
        rows = self._database.connection.execute(
            """
            SELECT b.id, b.account_id, a.name AS account_name, b.source_name,
                   b.review_mode, b.imported_at, b.row_count
            FROM import_batches b
            JOIN accounts a ON a.id=b.account_id AND a.book_id=b.book_id
            WHERE b.book_id=? ORDER BY b.id DESC LIMIT ?
            """,
            (book_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def batch_rows(self, book_id: int, batch_id: int) -> list[dict[str, object]]:
        batch = self._require_batch(book_id, batch_id)
        accounts = self._accounts.list_accounts(book_id)
        source_account_id = int(batch["account_id"])
        rows = self._database.connection.execute(
            """
            SELECT id, row_number, transaction_date, amount_minor, currency_code,
                   description, external_id, review_state, matched_transaction_id
            FROM import_rows WHERE book_id=? AND batch_id=? ORDER BY row_number
            """,
            (book_id, batch_id),
        ).fetchall()
        return [
            {
                **dict(row),
                "candidates": self._candidate_details(
                    book_id,
                    source_account_id,
                    str(row["transaction_date"]),
                    int(row["amount_minor"]),
                ),
                "postingCapabilities": self._posting_capabilities(
                    source_account_id=source_account_id,
                    currency_code=str(row["currency_code"]),
                    amount_minor=int(row["amount_minor"]),
                    accounts=accounts,
                ),
            }
            for row in rows
        ]

    def link_existing(
        self,
        *,
        book_id: int,
        row_id: int,
        transaction_id: int,
    ) -> dict[str, object]:
        row, batch = self._require_row(book_id, row_id)
        if str(row["review_state"]) in _TERMINAL_STATES:
            raise ReconciliationError("row is already resolved")
        candidate_ids = {
            int(item["id"])
            for item in self._candidate_details(
                book_id,
                int(batch["account_id"]),
                str(row["transaction_date"]),
                int(row["amount_minor"]),
            )
        }
        if transaction_id not in candidate_ids:
            raise ReconciliationError(
                "transaction is not compatible or is already reconciled"
            )
        with self._database.transaction() as conn:
            if row["external_id"] is not None:
                self._insert_link(
                    conn,
                    book_id=book_id,
                    account_id=int(batch["account_id"]),
                    source_name=str(batch["source_name"]),
                    external_id=str(row["external_id"]),
                    transaction_id=transaction_id,
                )
            conn.execute(
                """
                UPDATE import_rows
                SET review_state='MATCHED', matched_transaction_id=?
                WHERE id=? AND book_id=?
                """,
                (transaction_id, row_id, book_id),
            )
        return {"rowId": row_id, "transactionId": transaction_id, "state": "MATCHED"}

    def post_row(
        self,
        *,
        book_id: int,
        row_id: int,
        posting_kind: str,
        counter_account_id: int,
        payee_id: int | None = None,
    ) -> dict[str, object]:
        row, batch = self._require_row(book_id, row_id)
        state = str(row["review_state"])
        if state == "AMBIGUOUS":
            raise ReconciliationAmbiguousError(
                "ambiguous rows must be resolved before posting"
            )
        if state in _TERMINAL_STATES or state in _BLOCKED_POST_STATES:
            raise ReconciliationError("row cannot be posted in its current state")

        amount = int(row["amount_minor"])
        try:
            kind = PostingPolicy.normalize_kind(posting_kind)
        except ValueError as exc:
            raise ReconciliationError(
                "posting_kind must be EXPENSE, INCOME, REFUND or TRANSFER"
            ) from exc
        if kind not in PostingPolicy.allowed_kinds_for_amount(amount):
            raise ReconciliationError("posting kind is incompatible with imported amount sign")

        imported_account = self._accounts.get_account(book_id, int(batch["account_id"]))
        counter = self._accounts.get_account(book_id, counter_account_id)
        if imported_account.currency_code is None:
            raise ReconciliationError("imported account has no native currency")
        if not PostingPolicy.counter_is_eligible(
            kind,
            source_account_id=imported_account.id,
            source_currency=imported_account.currency_code,
            counter_account_id=counter.id,
            counter_type=counter.type,
            counter_currency=counter.currency_code,
            counter_archived=counter.archived,
            counter_placeholder=counter.placeholder,
        ):
            raise ReconciliationError("counter account is not eligible for this posting kind")

        common = {
            "book_id": book_id,
            "currency_code": str(row["currency_code"]),
            "transaction_date": str(row["transaction_date"]),
            "description": str(row["description"]),
        }
        with self._database.transaction() as conn:
            if kind == "EXPENSE":
                transaction = self._ledger.create_expense(
                    source_account_id=imported_account.id,
                    expense_account_id=counter.id,
                    amount_minor=-amount,
                    connection=conn,
                    **common,
                )
            elif kind == "INCOME":
                transaction = self._ledger.create_income(
                    destination_account_id=imported_account.id,
                    income_account_id=counter.id,
                    amount_minor=amount,
                    connection=conn,
                    **common,
                )
            elif kind == "REFUND":
                transaction = self._ledger.create_refund(
                    destination_account_id=imported_account.id,
                    expense_account_id=counter.id,
                    amount_minor=amount,
                    connection=conn,
                    **common,
                )
            elif amount < 0:
                transaction = self._ledger.create_transfer(
                    source_account_id=imported_account.id,
                    destination_account_id=counter.id,
                    amount_minor=-amount,
                    connection=conn,
                    **common,
                )
            else:
                transaction = self._ledger.create_transfer(
                    source_account_id=counter.id,
                    destination_account_id=imported_account.id,
                    amount_minor=amount,
                    connection=conn,
                    **common,
                )

            if payee_id is not None:
                self._payees.assign_transaction(
                    book_id=book_id,
                    transaction_id=transaction.id,
                    payee_id=payee_id,
                    connection=conn,
                )
            if row["external_id"] is not None:
                self._insert_link(
                    conn,
                    book_id=book_id,
                    account_id=imported_account.id,
                    source_name=str(batch["source_name"]),
                    external_id=str(row["external_id"]),
                    transaction_id=transaction.id,
                )
            conn.execute(
                """
                UPDATE import_rows
                SET review_state='POSTED', matched_transaction_id=?
                WHERE id=? AND book_id=?
                """,
                (transaction.id, row_id, book_id),
            )
        return {
            "rowId": row_id,
            "transactionId": transaction.id,
            "state": "POSTED",
        }

    def ignore_row(self, *, book_id: int, row_id: int) -> dict[str, object]:
        row, _ = self._require_row(book_id, row_id)
        if str(row["review_state"]) in _TERMINAL_STATES:
            raise ReconciliationError("row is already resolved")
        with self._database.transaction() as conn:
            conn.execute(
                """
                UPDATE import_rows SET review_state='IGNORED'
                WHERE id=? AND book_id=?
                """,
                (row_id, book_id),
            )
        return {"rowId": row_id, "state": "IGNORED"}

    def _initial_state(
        self,
        *,
        book_id: int,
        account_id: int,
        source_name: str,
        external_id: object,
        fingerprint: str,
        transaction_date: str,
        amount_minor: int,
        review_mode: str,
        tracking_start_date: str | None,
        tracking_start_time: str | None,
    ) -> tuple[str, int | None]:
        if external_id is not None:
            link = self._database.connection.execute(
                """
                SELECT transaction_id FROM reconciliation_links
                WHERE book_id=? AND account_id=? AND source_name=? AND external_id=?
                """,
                (book_id, account_id, source_name, str(external_id)),
            ).fetchone()
            if link is not None:
                linked_id = int(link["transaction_id"])
                if self._transaction_is_compatible(
                    book_id, account_id, linked_id, transaction_date, amount_minor
                ):
                    return "MATCHED", linked_id
                return "AMBIGUOUS", None

        if tracking_start_date is not None:
            boundary = TrackingBoundaryPolicy.classify(
                tracking_start_date=tracking_start_date,
                tracking_start_time=tracking_start_time,
                transaction_date=transaction_date,
                transaction_time=None,
            )
            if boundary.status is TrackingBoundaryStatus.BEFORE_BOUNDARY:
                return "OUTSIDE_TRACKING", None
            if boundary.status is TrackingBoundaryStatus.AMBIGUOUS:
                return "TRACKING_AMBIGUOUS", None

        if external_id is not None:
            duplicate = self._database.connection.execute(
                """
                SELECT 1
                FROM import_rows r
                JOIN import_batches b ON b.id=r.batch_id
                WHERE r.book_id=? AND b.account_id=? AND b.source_name=?
                  AND r.external_id=?
                LIMIT 1
                """,
                (book_id, account_id, source_name, str(external_id)),
            ).fetchone()
            if duplicate is not None:
                return "DUPLICATE_REVIEW", None
        else:
            duplicate = self._database.connection.execute(
                """
                SELECT 1
                FROM import_rows r
                JOIN import_batches b ON b.id=r.batch_id
                WHERE r.book_id=? AND b.account_id=? AND b.source_name=?
                  AND r.fingerprint=?
                LIMIT 1
                """,
                (book_id, account_id, source_name, fingerprint),
            ).fetchone()
            if duplicate is not None:
                return "DUPLICATE_REVIEW", None

        if review_mode == "FULL_REVIEW":
            return "REVIEW_REQUIRED", None
        candidate_count = len(
            self._candidate_details(book_id, account_id, transaction_date, amount_minor)
        )
        if candidate_count == 1:
            return "SUGGESTED", None
        if candidate_count > 1:
            return "AMBIGUOUS", None
        return "UNMATCHED", None

    def _posting_capabilities(
        self,
        *,
        source_account_id: int,
        currency_code: str,
        amount_minor: int,
        accounts,
    ) -> dict[str, list[int]]:
        capabilities: dict[str, list[int]] = {}
        for kind in PostingPolicy.allowed_kinds_for_amount(amount_minor):
            capabilities[kind] = [
                account.id
                for account in accounts
                if PostingPolicy.counter_is_eligible(
                    kind,
                    source_account_id=source_account_id,
                    source_currency=currency_code,
                    counter_account_id=account.id,
                    counter_type=account.type,
                    counter_currency=account.currency_code,
                    counter_archived=account.archived,
                    counter_placeholder=account.placeholder,
                )
            ]
        return capabilities

    def _candidate_details(
        self,
        book_id: int,
        account_id: int,
        transaction_date: str,
        amount_minor: int,
    ) -> list[dict[str, object]]:
        rows = self._database.connection.execute(
            """
            SELECT DISTINCT t.id, t.kind, t.transaction_date, t.currency_code,
                   t.description, COALESCE(p.name, '') AS payee_name
            FROM transactions t
            JOIN entries e ON e.transaction_id=t.id AND e.book_id=t.book_id
            LEFT JOIN payees p ON p.id=t.payee_id AND p.book_id=t.book_id
            WHERE t.book_id=? AND e.account_id=? AND t.transaction_date=?
              AND e.quantity_minor=?
              AND NOT EXISTS (
                  SELECT 1 FROM reconciliation_links l
                  WHERE l.book_id=t.book_id AND l.account_id=? AND l.transaction_id=t.id
              )
            ORDER BY t.id
            """,
            (book_id, account_id, transaction_date, amount_minor, account_id),
        ).fetchall()
        return [dict(row) for row in rows]

    def _transaction_is_compatible(
        self,
        book_id: int,
        account_id: int,
        transaction_id: int,
        transaction_date: str,
        amount_minor: int,
    ) -> bool:
        row = self._database.connection.execute(
            """
            SELECT 1
            FROM transactions t
            JOIN entries e ON e.transaction_id=t.id AND e.book_id=t.book_id
            WHERE t.id=? AND t.book_id=? AND e.account_id=?
              AND t.transaction_date=? AND e.quantity_minor=?
            LIMIT 1
            """,
            (transaction_id, book_id, account_id, transaction_date, amount_minor),
        ).fetchone()
        return row is not None

    def _require_batch(self, book_id: int, batch_id: int):
        row = self._database.connection.execute(
            "SELECT * FROM import_batches WHERE id=? AND book_id=?",
            (batch_id, book_id),
        ).fetchone()
        if row is None:
            raise ReconciliationError("unknown import batch")
        return row

    def _require_row(self, book_id: int, row_id: int):
        row = self._database.connection.execute(
            "SELECT * FROM import_rows WHERE id=? AND book_id=?",
            (row_id, book_id),
        ).fetchone()
        if row is None:
            raise ReconciliationError("unknown import row")
        return row, self._require_batch(book_id, int(row["batch_id"]))

    @staticmethod
    def _insert_link(
        conn,
        *,
        book_id: int,
        account_id: int,
        source_name: str,
        external_id: str,
        transaction_id: int,
    ) -> None:
        try:
            conn.execute(
                """
                INSERT INTO reconciliation_links(
                    book_id, account_id, source_name, external_id,
                    transaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, datetime('now'))
                """,
                (book_id, account_id, source_name, external_id, transaction_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ReconciliationAmbiguousError(
                "reconciliation identity is already linked"
            ) from exc

    @classmethod
    def _parse_csv(cls, text: str) -> list[dict[str, str]]:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            raise ReconciliationError("CSV header is missing")

        headers = [
            (cls._normalize_header(name), name)
            for name in reader.fieldnames
            if name is not None
        ]
        normalized_names = [item[0] for item in headers]
        if len(set(normalized_names)) != len(normalized_names):
            raise ReconciliationAmbiguousError("CSV contains duplicate normalized headers")

        date_col = cls._find_header(headers, _DATE_HEADERS, "date")
        amount_col = cls._find_header(headers, _AMOUNT_HEADERS, "amount")
        currency_col = cls._find_header(headers, _CURRENCY_HEADERS, None)
        description_col = cls._find_header(headers, _DESCRIPTION_HEADERS, None)
        external_col = cls._find_header(headers, _EXTERNAL_ID_HEADERS, None)

        result: list[dict[str, str]] = []
        for raw in reader:
            if raw is None or not any((value or "").strip() for value in raw.values()):
                continue
            result.append(
                {
                    "date": (raw.get(date_col) or "").strip(),
                    "amount": (raw.get(amount_col) or "").strip(),
                    "currency": (
                        (raw.get(currency_col) or "").strip() if currency_col else ""
                    ),
                    "description": (
                        (raw.get(description_col) or "").strip()
                        if description_col
                        else ""
                    ),
                    "external_id": (
                        (raw.get(external_col) or "").strip() if external_col else ""
                    ),
                }
            )
        return result

    @staticmethod
    def _normalize_header(value: str) -> str:
        return _HEADER_RE.sub("", value.strip().casefold())

    @staticmethod
    def _find_header(
        headers: list[tuple[str, str]],
        aliases: tuple[str, ...],
        required: str | None,
    ) -> str | None:
        alias_set = set(aliases)
        matches = [original for normalized, original in headers if normalized in alias_set]
        if len(matches) > 1:
            label = required or "optional field"
            raise ReconciliationAmbiguousError(
                f"CSV has multiple candidate columns for {label}: {', '.join(matches)}"
            )
        if matches:
            return matches[0]
        if required is not None:
            raise ReconciliationError(f"CSV column not found: {required}")
        return None

    @staticmethod
    def _parse_date(value: str, row_number: int) -> str:
        raw = value.strip()
        for parser in (
            lambda text: date.fromisoformat(text),
            lambda text: datetime.strptime(text, "%d/%m/%Y").date(),
            lambda text: datetime.strptime(text, "%d-%m-%Y").date(),
        ):
            try:
                return parser(raw).isoformat()
            except ValueError:
                pass
        raise ReconciliationError(f"row {row_number}: invalid date")

    @staticmethod
    def _normalize_source(value: str) -> str:
        if not isinstance(value, str):
            raise ReconciliationError("source_name is required")
        normalized = unicodedata.normalize("NFKC", value).strip().casefold()
        normalized = _SPACE_RE.sub(" ", normalized)
        if not normalized:
            raise ReconciliationError("source_name is required")
        return normalized

    @staticmethod
    def _fingerprint(
        account_id: int,
        transaction_date: str,
        amount_minor: int,
        currency_code: str,
        description: str,
    ) -> str:
        normalized_description = unicodedata.normalize("NFKC", description).strip().casefold()
        normalized_description = _SPACE_RE.sub(" ", normalized_description)
        payload = (
            f"{account_id}|{transaction_date}|{amount_minor}|{currency_code}|"
            f"{normalized_description}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
