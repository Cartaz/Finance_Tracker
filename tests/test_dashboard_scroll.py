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


def test_primary_scroll_regions_use_trackless_pill_scrollbars() -> None:
    styles = (_WEB_DIR / "styles.css").read_text(encoding="utf-8")

    regions = ".content,.setup,#cash-flow,#category-report,#merchant-report,#recent"
    assert f"{regions}{{scrollbar-width:thin;" in styles
    assert "scrollbar-color:rgba(135,135,135,.42) transparent" in styles
    assert "::-webkit-scrollbar-track" in styles
    assert "background:transparent" in styles
    assert "::-webkit-scrollbar-thumb" in styles
    assert "background-clip:content-box" in styles
    assert "border:2px solid transparent" in styles
    assert "border-radius:999px" in styles
    assert "min-height:28px" in styles
    assert "::-webkit-scrollbar-button" in styles
    assert "display:none;width:0;height:0" in styles
