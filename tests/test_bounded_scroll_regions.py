from __future__ import annotations

from pathlib import Path

_WEB_DIR = Path(__file__).resolve().parents[1] / "ui" / "web"


def test_operational_lists_share_the_fixed_scroll_indicator() -> None:
    script = (_WEB_DIR / "scroll-indicators.js").read_text(encoding="utf-8")

    for region_id in (
        "transactions-list",
        "accounts-list",
        "categories-list",
        "budget-list",
        "loan-list",
        "loan-detail",
    ):
        assert f'["{region_id}",' in script

    assert 'region.dataset.scrollIndicator = ""' in script
    assert 'region.tabIndex = 0' in script
    assert 'region.setAttribute("role", "region")' in script
    assert 'link.href = "scroll-regions.css"' in script
    assert 'region.addEventListener("wheel"' not in script
    assert 'region.addEventListener("keydown"' not in script


def test_list_heights_are_driven_by_their_logical_left_hand_cards() -> None:
    script = (_WEB_DIR / "scroll-indicators.js").read_text(encoding="utf-8")
    styles = (_WEB_DIR / "scroll-regions.css").read_text(encoding="utf-8")

    for source_id, target_id in (
        ("transaction-create-heading", "transactions-list"),
        ("account-create-heading", "account-overview-heading"),
        ("budget-form", "budget-list"),
        ("loan-form", "loan-list"),
    ):
        assert f'sourceId: "{source_id}"' in script
        assert f'targetId: "{target_id}"' in script

    assert 'state.target.style.setProperty("--logic-height"' in script
    assert 'new ResizeObserver(scheduleUpdate)' in script
    assert '.logic-height-source{align-self:start}' in styles
    assert 'max-height:var(--logic-height)' in styles
    assert (
        '.loan-output-bound{display:grid!important;grid-template-rows:'
        'minmax(0,2fr) minmax(0,3fr)' in styles
    )


def test_budget_and_loan_outputs_are_flat_lists_not_nested_neumorphic_cards() -> None:
    styles = (_WEB_DIR / "scroll-regions.css").read_text(encoding="utf-8")
    app_js = (_WEB_DIR / "app.js").read_text(encoding="utf-8")

    assert '#budget-list>.card,#loan-list>.card{background:transparent;' in styles
    assert 'box-shadow:none' in styles
    assert '#budget-list [data-budget-delete]' in styles
    assert '-webkit-mask:url("data:image/svg+xml' in styles
    assert 'data-budget-delete="${item.id}"' in app_js
    assert 'call("deleteBudget"' in app_js
    assert '#loan-detail>h3{' in styles
    assert '#loan-detail>.form-card{' in styles


def test_narrow_layout_keeps_lists_bounded_without_height_pairing() -> None:
    styles = (_WEB_DIR / "scroll-regions.css").read_text(encoding="utf-8")

    assert '@media(max-width:1000px)' in styles
    assert '.bounded-scroll-card{max-height:none}' in styles
    assert '.loan-output-bound{height:auto;max-height:none;grid-template-rows:auto auto}' in styles
    assert 'max-height:calc(var(--dashboard-row-height)*5)' in styles
