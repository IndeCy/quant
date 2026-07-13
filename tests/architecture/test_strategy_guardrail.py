"""策略声明变更围栏测试。"""

from scripts.check_strategy_boundaries import compare_strategy_payloads


def test_strategy_logic_change_requires_version_bump() -> None:
    """修改 TopN 却不提升版本必须失败。"""
    previous = {"strategy_id": "quality", "version": "1.0.0", "construction": {"top_n": 20}}
    current = {"strategy_id": "quality", "version": "1.0.0", "construction": {"top_n": 40}}

    assert compare_strategy_payloads(previous, current, "quality.json") == [
        "quality.json: 策略定义已变化，但版本仍为 1.0.0"
    ]


def test_version_bump_allows_strategy_definition_change() -> None:
    """明确提升版本后才允许业务定义变化。"""
    previous = {"strategy_id": "quality", "version": "1.0.0", "construction": {"top_n": 20}}
    current = {"strategy_id": "quality", "version": "1.1.0", "construction": {"top_n": 40}}

    assert compare_strategy_payloads(previous, current, "quality.json") == []
