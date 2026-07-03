#!/usr/bin/env python3
"""运行投研机会池每日研究监控。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.tushare_concept_incremental import update_opportunity_concept_cache
from runtime.opportunity_catalog import register_builtin_opportunity_themes
from runtime.opportunity_verifier import THEME_CONCEPT_KEYWORDS, verify_opportunity_seed_stocks
from runtime.notification_config import send_bark_notification
from runtime.paths import get_runtime_paths
from runtime.repository import SystemRepository
from runtime.research_monitor import format_research_monitor_notification, run_research_monitor


def main() -> None:
    """命令行入口，供 APScheduler 调用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="运行完成后发送投研监控 Bark 摘要")
    args = parser.parse_args()
    paths = get_runtime_paths()
    register_builtin_opportunity_themes(SystemRepository(paths.system_state_path))
    try:
        update_opportunity_concept_cache(paths.data_dir / "opportunity_concept_increment.duckdb", THEME_CONCEPT_KEYWORDS)
    except Exception as exc:
        print(f"概念缓存更新失败，继续使用已有缓存: {exc}", file=sys.stderr)
    verify_opportunity_seed_stocks(paths)
    result = run_research_monitor(paths)
    if args.push:
        send_bark_notification("量化投研监控SUCCESS", format_research_monitor_notification(result))
    print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
