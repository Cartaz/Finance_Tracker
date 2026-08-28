from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_dashboard_lists_are_bounded_to_five_visible_rows() -> None:
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "--dashboard-row-height:56px" in styles
    assert (
        "#cash-flow,#category-report,#merchant-report,#recent{"
        "max-height:calc(var(--dashboard-row-height)*5);overflow-y:auto;"
        "overflow-x:hidden;overscroll-behavior:contain;scrollbar-gutter:stable;"
        "padding-right:6px}"
        in styles
    )
    assert (
        "#cash-flow>.report-row,#category-report>.report-row,"
        "#merchant-report>.report-row,#recent>.row{"
        "min-height:var(--dashboard-row-height)}"
        in styles
    )


def test_primary_scroll_regions_use_qt_webengine_trackless_pill_scrollbars() -> None:
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")

    assert "scrollbar-width:" not in styles
    assert "scrollbar-color:" not in styles
    assert "::-webkit-scrollbar{width:6px;height:6px;background:transparent}" in styles
    assert "::-webkit-scrollbar-track-piece" in styles
    assert "::-webkit-scrollbar-corner" in styles
    assert "background:rgba(135,135,135,.42)" in styles
    assert "background-clip:content-box" in styles
    assert "border:1px solid transparent" in styles
    assert "border-radius:999px" in styles
    assert "min-height:30px" in styles
    assert "::-webkit-scrollbar-button:single-button" in styles
    assert "::-webkit-scrollbar-button:vertical:decrement" in styles
    assert "::-webkit-scrollbar-button:vertical:increment" in styles
    assert (
        "display:none!important;width:0!important;height:0!important;"
        "background:transparent!important"
        in styles
    )
