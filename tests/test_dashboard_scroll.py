from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_dashboard_lists_are_bounded_to_five_visible_rows() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "--dashboard-row-height:56px" in styles
    assert (
        "#cash-flow,#category-report,#merchant-report,#recent{"
        "max-height:calc(var(--dashboard-row-height)*5);overflow-y:auto;"
        "overflow-x:hidden;overscroll-behavior:contain;padding-right:8px}"
        in styles
    )
    assert (
        "#cash-flow>.report-row,#category-report>.report-row,"
        "#merchant-report>.report-row,#recent>.row{"
        "min-height:var(--dashboard-row-height)}"
        in styles
    )
    for element_id in ("cash-flow", "category-report", "merchant-report", "recent"):
        assert f'id="{element_id}" data-scroll-indicator tabindex="0" role="region"' in index


def test_fixed_scroll_indicators_keep_native_scrolling_and_hide_native_chrome() -> None:
    index = (_WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")
    frontend = (_WEB_DIR / "scroll-indicators.js").read_text(encoding="utf-8")

    assert '<main class="content" data-scroll-indicator>' in index
    assert '<section id="setup" class="setup hidden" data-scroll-indicator>' in index
    assert '<script src="scroll-indicators.js"></script>' in index

    assert "[data-scroll-indicator]{scrollbar-width:none;-ms-overflow-style:none}" in styles
    assert (
        "[data-scroll-indicator]::-webkit-scrollbar{width:0;height:0;display:none}"
        in styles
    )
    assert ".scroll-pill-indicator{position:fixed;z-index:18;width:4px;height:18px;" in styles
    assert "border-radius:999px" in styles
    assert ".scroll-pill-indicator.visible{opacity:.58;pointer-events:auto;cursor:grab}" in styles
    assert ".scroll-pill-indicator.dragging{cursor:grabbing}" in styles

    assert 'document.querySelectorAll("[data-scroll-indicator]").forEach(bindRegion)' in frontend
    assert "region.scrollHeight - region.clientHeight" in frontend
    assert "region.scrollTop / maxScroll" in frontend
    assert "pill.offsetHeight" in frontend
    assert "state.region.scrollTop = state.dragStartScroll + (" in frontend
    assert "ResizeObserver" in frontend
    assert "MutationObserver" in frontend
    assert 'region.addEventListener("scroll"' in frontend
    assert 'addEventListener("wheel"' not in frontend
    assert 'addEventListener("keydown"' not in frontend
