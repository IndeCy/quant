#!/usr/bin/env python3
"""运行所有已启用策略实例。"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.strategy_batch_runner import run_enabled_strategy_instances


def main() -> None:
    """命令行入口，供 APScheduler 调用。"""
    summary = run_enabled_strategy_instances()
    print(summary)


if __name__ == "__main__":
    main()
