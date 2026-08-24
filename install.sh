#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [[ ! -f requirements.txt ]]; then
  echo "[ERROR] requirements.txt not found in $ROOT_DIR" >&2
  exit 1
fi

PYTHON_BIN=""
for candidate in python3.14 python3.13 python3.12 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" - <<'PY' >/dev/null 2>&1
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY
    then
      PYTHON_BIN="$candidate"
      break
    fi
  fi
done

if [[ -z "$PYTHON_BIN" ]]; then
  echo "[ERROR] Python 3.12+ is required." >&2
  exit 1
fi

echo "[INFO] Using $($PYTHON_BIN --version)"

if [[ ! -x .venv/bin/python ]]; then
  echo "[INFO] Creating virtual environment"
  rm -rf .venv
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt

.venv/bin/python - <<'PY'
import PySide6
import sqlite3
print(f"[OK] PySide6 {PySide6.__version__}")
print(f"[OK] SQLite {sqlite3.sqlite_version}")
PY

echo "[OK] Installation complete"
echo "[INFO] Launch with: .venv/bin/python main.py"
