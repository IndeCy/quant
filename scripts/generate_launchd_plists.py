#!/usr/bin/env python3
"""生成本地量化系统 launchd plist 模板。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import get_runtime_paths
from runtime.service_manager import build_service_manifest


def main() -> None:
    """把 plist 模板写入运行目录 config/launchd。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    paths = get_runtime_paths()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else paths.config_dir / "launchd"
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_service_manifest(paths)
    for service in manifest["services"]:
        path = output_dir / f"{service['label']}.plist"
        path.write_text(str(service["launchd_plist"]), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
