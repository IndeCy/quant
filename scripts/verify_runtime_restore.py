#!/usr/bin/env python3
"""验收迁移后的量化运行目录。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import RuntimePaths
from runtime.restore_audit import audit_runtime_restore


def main() -> int:
    """打印机器可读验收结果，失败时返回非零退出码。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--config-path", default="")
    args = parser.parse_args()
    config_path = Path(args.config_path).expanduser().resolve() if args.config_path else None
    result = audit_runtime_restore(RuntimePaths(Path(args.runtime_root).expanduser().resolve()), config_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
