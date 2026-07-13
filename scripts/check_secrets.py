#!/usr/bin/env python3
"""扫描 Git 跟踪文本中的常见本地密钥。"""

from __future__ import annotations

from pathlib import Path
import re
import subprocess


PATTERNS = {
    "Bark设备密钥": re.compile(r"api\.day\.app/[A-Za-z0-9]{20,}"),
    "Tushare明文Token": re.compile(r"TUSHARE_TOKEN\s*=\s*[A-Za-z0-9]{20,}"),
}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".json", ".md", ".toml", ".yaml", ".yml", ".properties", ".sh"}


def main() -> int:
    """只扫描 Git 跟踪文件，避免读取本地 `.env.properties`。"""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    errors: list[str] = []
    for relative in result.stdout.splitlines():
        path = root / relative
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        content = path.read_text(encoding="utf-8", errors="ignore")
        for name, pattern in PATTERNS.items():
            if pattern.search(content):
                errors.append(f"{relative}: 检测到{name}")
    if errors:
        print("敏感信息检查失败：")
        for error in sorted(errors):
            print(f"- {error}")
        return 1
    print("敏感信息检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
