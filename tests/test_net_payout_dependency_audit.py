"""净派息组合依赖门禁测试。"""

from examples import net_payout_dependency_audit as study


def test_failed_dependency_blocks_combination(tmp_path, monkeypatch) -> None:
    """任一基础研究失败时不得扫描数据或回测组合。"""
    class Repository:
        def __init__(self, path) -> None:
            self.path = path

        def load_experiment_detail(self, experiment_id: str):
            return {
                "latest_run": {
                    "status": "SUCCESS",
                    "outcome": (
                        "REJECTED"
                        if "share_issuance" in experiment_id
                        else "PASSED_RESEARCH_GATE"
                    ),
                    "decision_reason": "测试结论",
                }
            }

    monkeypatch.setattr(study, "SystemRepository", Repository)
    result = study.run_study(study.RuntimePaths(tmp_path), "20260726")

    assert result["passed"] is False
    assert result["decision"] == "REJECTED_BEFORE_DATA_SCAN"
