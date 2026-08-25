#!/usr/bin/env python3
"""Generate deterministic Finance Tracker bug-hunting CSV stress fixtures."""

from __future__ import annotations

import csv
from pathlib import Path


HEADERS = ["date", "amount", "currency", "description", "external_id"]
DESCRIPTIONS = (
    "Supermercato, spesa settimanale",
    "Stipendio mensile",
    "Bonifico affitto",
    "Caffè e colazione",
    "Rimborso acquisto",
    'Descrizione con "virgolette"',
    "Pagamento carta - online",
    "Abbonamento palestra",
    "Benzina / carburante",
    "Acquisto € unicode",
)


def row_for(index: int) -> list[str]:
    day = (index % 28) + 1
    month = ((index // 28) % 12) + 1
    year = 2024 + ((index // (28 * 12)) % 3)
    transaction_date = f"{year:04d}-{month:02d}-{day:02d}"
    cents = ((index * 137) % 250_000) + 1
    sign = -1 if index % 4 != 0 else 1
    amount = f"{sign * cents / 100:.2f}"
    return [transaction_date, amount, "EUR", DESCRIPTIONS[index % len(DESCRIPTIONS)], f"BUG-HUNT-{index:05d}"]


def padded_row_for(index: int, description_length: int) -> list[str]:
    return [
        f"2026-08-{(index % 28) + 1:02d}",
        "-12.34",
        "EUR",
        "X" * description_length,
        f"SIZE-{index:05d}",
    ]


def write_fixture(path: Path, row_count: int, *, description_length: int | None = None) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for index in range(1, row_count + 1):
            writer.writerow(
                row_for(index)
                if description_length is None
                else padded_row_for(index, description_length)
            )


def main() -> None:
    destination = Path(__file__).resolve().parent / "generated"
    destination.mkdir(parents=True, exist_ok=True)
    write_fixture(destination / "bug-hunting-test-reconciliation-10000-valid.csv", 10_000)
    write_fixture(destination / "bug-hunting-test-reconciliation-10001-too-many.csv", 10_001)
    # 9,500 rows keep row count below the limit. Description padding targets the byte-size boundary.
    write_fixture(
        destination / "bug-hunting-test-reconciliation-near-10mb-valid.csv",
        9_500,
        description_length=1_000,
    )
    write_fixture(
        destination / "bug-hunting-test-reconciliation-over-10mb.csv",
        9_500,
        description_length=1_050,
    )
    for path in sorted(destination.glob("*.csv")):
        print(f"{path.name}: {path.stat().st_size} bytes")


if __name__ == "__main__":
    main()
