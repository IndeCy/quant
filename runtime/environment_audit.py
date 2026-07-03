from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
from typing import Mapping

from runtime.config import default_config_path, load_properties_file


LAUNCHD_FILES = {
    "api_launchd": "com.quant.api.plist",
    "scheduler_launchd": "com.quant.scheduler.plist",
    "frontend_launchd": "com.quant.frontend.plist",
}
BARK_KEYS = ("BARK_PUSH_URL", "BARK_URL", "QUANT_BARK_URL")


def build_environment_audit(
    env: Mapping[str, str] | None = None,
    launch_agents_dir: Path | None = None,
    config_path: Path | None = None,
) -> dict[str, object]:
    """构建运行环境一致性审计结果，避免不同进程读取到不同关键配置。"""
    process_env = dict(env or os.environ)
    launch_dir = launch_agents_dir or Path.home() / "Library" / "LaunchAgents"
    raw_sources = _load_sources(process_env, launch_dir, config_path or default_config_path())
    checks = [
        _required_value_check(
            "TUSHARE_TOKEN",
            raw_sources,
            ("config_file",),
            "把 TUSHARE_TOKEN 写入项目根目录 .env.properties，避免不同进程读取不同环境。",
        ),
        _required_value_check(
            "QUANT_HOME",
            raw_sources,
            ("process", "api_launchd", "scheduler_launchd", "frontend_launchd"),
            "统一 QUANT_HOME，确保终端、API、调度器和前端都指向同一个项目目录。",
        ),
        _bark_channel_check(raw_sources),
    ]
    sanitized_sources = {
        source: {
            key: _value_summary(raw_env.get(key, ""))
            for key in ("QUANT_HOME", "TUSHARE_TOKEN", *BARK_KEYS)
            if key in raw_env
        }
        for source, raw_env in raw_sources.items()
    }
    payload: dict[str, object] = {
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "secret_values_exposed": False,
        "sources": sanitized_sources,
        "checks": checks,
    }
    payload["secret_values_exposed"] = _contains_raw_secret(payload, raw_sources)
    return payload


def _load_sources(process_env: Mapping[str, str], launch_agents_dir: Path, config_path: Path) -> dict[str, dict[str, str]]:
    sources = {"process": dict(process_env), "config_file": load_properties_file(config_path)}
    for source, filename in LAUNCHD_FILES.items():
        sources[source] = _read_launchd_env(launch_agents_dir / filename)
    return sources


def _read_launchd_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as file:
            payload = plistlib.load(file)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}
    env = payload.get("EnvironmentVariables", {})
    if not isinstance(env, dict):
        return {}
    return {str(key): str(value) for key, value in env.items()}


def _required_value_check(
    name: str,
    sources: Mapping[str, Mapping[str, str]],
    required_sources: tuple[str, ...],
    recommendation: str,
) -> dict[str, object]:
    present_values = {
        source: sources.get(source, {}).get(name, "")
        for source in required_sources
        if sources.get(source, {}).get(name)
    }
    missing_in = [source for source in required_sources if not sources.get(source, {}).get(name)]
    fingerprints = {source: _fingerprint(value) for source, value in present_values.items()}
    unique_fingerprints = {value for value in fingerprints.values() if value}
    mismatch_sources = list(fingerprints) if len(unique_fingerprints) > 1 else []
    status = "PASS" if not missing_in and not mismatch_sources else "FAIL"
    return {
        "name": name,
        "status": status,
        "required_sources": list(required_sources),
        "missing_in": missing_in,
        "mismatch_sources": mismatch_sources,
        "fingerprints": fingerprints,
        "recommendation": "" if status == "PASS" else recommendation,
    }


def _bark_channel_check(sources: Mapping[str, Mapping[str, str]]) -> dict[str, object]:
    candidates: dict[str, str] = {}
    for source in ("config_file", "process", "scheduler_launchd"):
        for key in BARK_KEYS:
            value = sources.get(source, {}).get(key, "")
            if value:
                candidates[f"{source}.{key}"] = _fingerprint(value)
    status = "PASS" if candidates else "FAIL"
    return {
        "name": "BARK_CHANNEL",
        "status": status,
        "required_sources": ["config_file", "process", "scheduler_launchd"],
        "missing_in": [] if candidates else ["config_file", "process", "scheduler_launchd"],
        "mismatch_sources": [],
        "fingerprints": candidates,
        "recommendation": "" if status == "PASS" else "在 .env.properties 配置 Bark 推送地址，确保调度异常可以触达手机。",
    }


def _value_summary(value: str) -> dict[str, object]:
    return {"present": bool(value), "fingerprint": _fingerprint(value)}


def _fingerprint(value: str) -> str:
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]


def _contains_raw_secret(payload: Mapping[str, object], sources: Mapping[str, Mapping[str, str]]) -> bool:
    serialized = json.dumps(payload, ensure_ascii=False)
    for source_env in sources.values():
        for key, value in source_env.items():
            if key in {"TUSHARE_TOKEN", *BARK_KEYS} and value and value in serialized:
                return True
    return False
