from __future__ import annotations

from pathlib import Path

from examples import margin_flow_breadth_regime_feasibility_study as study
from runtime.paths import RuntimePaths


def test_definition_uses_source_counts_without_returns() -> None:
    definition = study.RESEARCH_SPEC.definition

    assert definition["indicator"] == "positive_count/valid_count"
    assert definition["outcome_returns_loaded"] is False


def test_resolve_migrated_artifact_uses_same_experiment_and_run(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(root=tmp_path)
    expected = (
        tmp_path
        / "runs"
        / "experiments"
        / "source_v1"
        / "run-1"
        / "monthly.csv"
    )
    expected.parent.mkdir(parents=True)
    expected.write_text("x\n", encoding="utf-8")

    resolved = study.resolve_migrated_artifact_path(
        paths,
        Path("/Users/admin/project/run-1/monthly.csv"),
        "source_v1",
    )

    assert resolved == expected
