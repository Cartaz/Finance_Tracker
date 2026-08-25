from pathlib import Path

from config.settings import Settings, SettingsStore


def test_missing_settings_use_defaults(tmp_path: Path) -> None:
    settings = SettingsStore(tmp_path / "settings.json").load()
    assert settings.book_currency == "EUR"
    assert settings.reconciliation_review_mode == "FULL_REVIEW"


def test_settings_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    settings = Settings(book_currency="usd", reconciliation_review_mode="ASSISTED_REVIEW")
    store.save(settings)
    loaded = store.load()
    assert loaded.book_currency == "USD"
    assert loaded.reconciliation_review_mode == "ASSISTED_REVIEW"


def test_invalid_settings_fall_back_to_defaults(tmp_path: Path, caplog) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"book_currency":"TOO_LONG"}', encoding="utf-8")
    with caplog.at_level("WARNING", logger="config.settings"):
        settings = SettingsStore(path).load()
    assert settings.book_currency == "EUR"
    assert "using defaults" in caplog.text


def test_malformed_settings_are_diagnosed_and_fall_back(tmp_path: Path, caplog) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not-json", encoding="utf-8")
    with caplog.at_level("WARNING", logger="config.settings"):
        settings = SettingsStore(path).load()
    assert settings.book_currency == "EUR"
    assert "Could not load settings" in caplog.text
    assert "using defaults" in caplog.text
