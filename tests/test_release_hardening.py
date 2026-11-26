from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_repairs_venv_and_verifies_qt_quick() -> None:
    installer = (ROOT / "install.sh").read_text(encoding="utf-8")

    assert "venv_usable()" in installer
    assert "Creating or repairing virtual environment" in installer
    assert "requirements-dev.txt" in installer
    assert "QQmlApplicationEngine" in installer
    assert "WebEngine" not in installer
    assert ".venv/bin/python main.py" in installer


def test_ci_exercises_external_cwd_and_supported_python_range() -> None:
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")

    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow
    assert "actions/checkout@v4" not in workflow
    assert "actions/setup-python@v5" not in workflow
    assert "cd /tmp" in workflow
    assert 'python-version: ["3.12", "3.14"]' in workflow
