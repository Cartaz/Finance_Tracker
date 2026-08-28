from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_account_section_uses_accessible_neumorphic_tabs() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")
    tabs_js = (_WEB_DIR / "account-tabs.js").read_text(encoding="utf-8")

    assert 'data-tab-group="account-create"' in index
    assert 'data-tab-group="account-overview"' in index
    assert index.count('role="tablist"') == 2
    assert index.count('role="tab"') == 4
    assert index.count('role="tabpanel"') == 4
    assert 'aria-controls="account-create-account-panel"' in index
    assert 'aria-controls="account-create-category-panel"' in index
    assert 'aria-controls="account-overview-account-panel"' in index
    assert 'aria-controls="account-overview-category-panel"' in index
    assert 'id="account-create-category-panel" class="tab-panel hidden"' in index
    assert 'id="account-overview-category-panel" class="tab-panel hidden"' in index
    assert '<script src="account-tabs.js"></script>' in index

    # The original forms remain separate; tabs own presentation state only.
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
