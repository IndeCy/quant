"""本地 KV 配置读取，统一承载私密 token 和运行开关。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


CONFIG_FILENAME = ".env.properties"


def project_root() -> Path:
    """定位项目根目录，避免依赖当前工作目录。"""
    return Path(__file__).resolve().parents[1]


def default_config_path() -> Path:
    """返回默认本地私密配置文件路径。"""
    return project_root() / CONFIG_FILENAME


def load_properties_file(path: Path | None = None) -> dict[str, str]:
    """读取 Java properties 风格的 key=value 文件。"""
    config_path = path or default_config_path()
    if not config_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in config_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def get_config_value(
    key: str,
    default: str = "",
    *,
    config_path: Path | None = None,
    environ: Mapping[str, str] | None = None,
    prefer_environ: bool = False,
) -> str:
    """按本地配置文件优先、环境变量兜底的顺序读取配置。"""
    env = environ if environ is not None else os.environ
    if prefer_environ and str(env.get(key, "")).strip():
        return str(env.get(key, "")).strip()
    file_values = load_properties_file(config_path)
    if key in file_values:
        return file_values[key].strip()
    return str(env.get(key, default)).strip()


def get_config_flag(key: str, default: bool = False, *, config_path: Path | None = None) -> bool:
    """读取布尔开关，只有显式真值才开启。"""
    raw_default = "true" if default else ""
    return get_config_value(key, raw_default, config_path=config_path).lower() in {"1", "true", "yes", "on"}
