"""科技ETF反转流动性修订门禁测试。"""

from examples import (
    a_share_tech_etf_weekly_reversal_liquid_feasibility_v2 as study,
)


def test_revision_excludes_only_failed_liquidity_asset() -> None:
    universe = study.RESEARCH_SPEC.definition["universe"]

    assert set(universe["included"]) == (
        set(study.tech.TECH_SYMBOLS) - {study.EXCLUDED}
    )
    assert universe["return_metrics_used_for_revision"] is False
    assert study.RESEARCH_SPEC.definition["further_universe_revision"] == "forbidden"


def test_signal_definition_is_unchanged_from_v1() -> None:
    assert (
        study.RESEARCH_SPEC.definition["signal_preview"]
        == study.v1.RESEARCH_SPEC.definition["signal_preview"]
    )
