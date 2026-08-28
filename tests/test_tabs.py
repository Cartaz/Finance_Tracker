from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_shared_tabs_are_accessible_and_presentation_only() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")
    tabs_js = (_WEB_DIR / "tabs.js").read_text(encoding="utf-8")

    assert 'data-tab-group="account-create"' in index
    assert 'data-tab-group="account-overview"' in index
    assert 'data-tab-group="tools"' in index
    assert index.count('role="tablist"') == 3
    assert index.count('role="tab"') == 7
    assert index.count('role="tabpanel"') == 7
    assert '<script src="tabs.js"></script>' in index
    assert 'account-tabs.js' not in index

    # Account/category behavior remains in separate forms; tabs only select presentation.
    assert 'id="account-form" class="form-card embedded-form"' in index
    assert 'id="category-form" class="form-card embedded-form"' in index

    assert ".section-tabs{" in styles
    assert ".section-tab.active,.section-tab[aria-selected=\"true\"]{" in styles
    assert ".tab-panel{min-width:0}" in styles

    assert 'item.setAttribute("aria-selected", selected ? "true" : "false")' in tabs_js
    assert 'item.tabIndex = selected ? 0 : -1' in tabs_js
    assert 'panel.classList.toggle("hidden", !selected)' in tabs_js
    assert 'ArrowRight: "next"' in tabs_js
    assert 'ArrowLeft: "previous"' in tabs_js
    assert 'Home: "first"' in tabs_js
    assert 'End: "last"' in tabs_js


def test_tools_workspace_groups_support_features_without_leaking_into_accounts() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert index.count('data-view="tools"') == 1
    assert 'data-view="reconciliation"' not in index
    assert 'data-view="backup"' not in index
    assert 'id="tools" class="view hidden"' in index

    assert 'id="tools-backup-panel"' in index
    assert 'id="tools-reconciliation-panel"' in index
    assert 'id="tools-fx-panel"' in index
    assert '>Backup</button>' in index
    assert '>Riconciliazione</button>' in index
    assert '>Valute e cambi</button>' in index

    accounts_section = index.split('<section id="accounts" class="view hidden">', 1)[1].split(
        '<section id="budgets" class="view hidden">', 1
    )[0]
    tools_section = index.split('<section id="tools" class="view hidden">', 1)[1]
    assert 'id="fx-form"' not in accounts_section
    assert 'id="fx-form"' in tools_section
    assert 'id="import-form"' in tools_section
    assert 'id="backup-list"' in tools_section

    assert ".tools-shell{" in styles
    assert ".tool-grid{" in styles
    assert ".tool-card{padding:20px;border-radius:16px;" in styles
    assert ".tool-span-full{grid-column:1/-1}" in styles
