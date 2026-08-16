"""完整研究批次元审计测试。"""

from pathlib import Path

from examples import research_campaign_20260729_meta_audit_v2 as audit
from runtime.paths import RuntimePaths


def test_campaign_has_no_duplicate_experiment_ids() -> None:
    ids = [
        experiment_id
        for values in audit.CAMPAIGN.values()
        for experiment_id in values
    ]

    assert len(ids) == len(set(ids))


def test_definition_never_recomputes_or_overrides_decisions() -> None:
    definition = audit.RESEARCH_SPEC.definition

    assert definition["does_not_recompute_returns"] is True
    assert definition["does_not_override_decisions"] is True


def test_resolve_path_maps_legacy_root_without_touching_other_paths(
    tmp_path: Path,
) -> None:
    paths = RuntimePaths(root=tmp_path)

    assert audit.resolve_path(
        paths,
        "/Users/admin/PycharmProjects/quant/runs/a.txt",
    ) == tmp_path / "runs/a.txt"
    assert audit.resolve_path(paths, "/tmp/a.txt") == Path("/tmp/a.txt")
