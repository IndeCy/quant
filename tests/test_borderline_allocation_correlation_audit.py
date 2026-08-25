from __future__ import annotations

from pathlib import Path

import numpy as np

from examples import borderline_allocation_correlation_audit as audit
from runtime.paths import RuntimePaths


def test_block_bootstrap_is_deterministic_and_preserves_high_correlation() -> None:
    rng = np.random.default_rng(7)
    left = rng.normal(size=500)
    right = left * 0.8 + rng.normal(scale=0.2, size=500)

    first = audit.paired_block_bootstrap_correlations(
        left,
        right,
        block_size=20,
        samples=200,
        seed=11,
    )
    second = audit.paired_block_bootstrap_correlations(
        left,
        right,
        block_size=20,
        samples=200,
        seed=11,
    )

    assert np.array_equal(first, second)
    assert float(np.quantile(first, 0.05)) > 0.80


def test_classification_never_overrides_borderline_base_gate() -> None:
    metrics = {
        "pearson": 0.51,
        "bootstrap": {"probability_above_limit": 0.60},
    }

    assert audit.classify_correlation(metrics) == "BORDERLINE_UNCERTAIN_NO_OVERRIDE"


def test_same_fingerprint_skips_heavy_calculation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    paths.system_state_path.touch()
    paths.monitoring_path.touch()
    attempt = audit.begin_research_attempt(
        audit.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260728",
        data_version=audit._data_version(paths),
    )
    audit.complete_research_attempt(
        attempt,
        metrics={"conclusion": {}},
        outcome="COMPLETED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中研究指纹后不得重复计算")

    monkeypatch.setattr(audit, "_calculate", fail_if_calculated)

    result = audit.run_audit(paths, "20260728")

    assert result["reused"] is True
