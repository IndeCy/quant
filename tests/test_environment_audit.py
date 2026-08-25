from pathlib import Path
import plistlib

from runtime.environment_audit import build_environment_audit


def _write_plist(path: Path, env: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"Label": path.stem, "EnvironmentVariables": env}
    with path.open("wb") as file:
        plistlib.dump(payload, file)


def test_environment_audit_detects_missing_properties_tushare_token(tmp_path: Path) -> None:
    launch_dir = tmp_path / "LaunchAgents"
    _write_plist(launch_dir / "com.quant.api.plist", {"QUANT_HOME": "/tmp/quant"})
    _write_plist(
        launch_dir / "com.quant.scheduler.plist",
        {"QUANT_HOME": "/tmp/quant", "TUSHARE_TOKEN": "secret-token"},
    )

    audit = build_environment_audit(
        env={"QUANT_HOME": "/tmp/quant"},
        launch_agents_dir=launch_dir,
        config_path=tmp_path / ".env.properties",
    )

    assert audit["status"] == "FAIL"
    assert audit["secret_values_exposed"] is False
    names = {item["name"]: item for item in audit["checks"]}
    assert names["TUSHARE_TOKEN"]["status"] == "FAIL"
    assert "config_file" in names["TUSHARE_TOKEN"]["missing_in"]


def test_environment_audit_passes_when_required_sources_match(tmp_path: Path) -> None:
    launch_dir = tmp_path / "LaunchAgents"
    config_path = tmp_path / ".env.properties"
    env = {
        "QUANT_HOME": "/tmp/quant",
        "TUSHARE_TOKEN": "secret-token",
        "BARK_PUSH_URL": "https://api.day.app/key",
    }
    config_path.write_text("TUSHARE_TOKEN=secret-token\nBARK_PUSH_URL=https://api.day.app/key\n", encoding="utf-8")
    _write_plist(launch_dir / "com.quant.api.plist", env)
    _write_plist(launch_dir / "com.quant.scheduler.plist", env)
    _write_plist(launch_dir / "com.quant.frontend.plist", {"QUANT_HOME": "/tmp/quant"})

    audit = build_environment_audit(env=env, launch_agents_dir=launch_dir, config_path=config_path)

    assert audit["status"] == "PASS"
    assert audit["secret_values_exposed"] is False
    assert all(item["status"] == "PASS" for item in audit["checks"])


def test_environment_audit_accepts_properties_file_as_runtime_config(tmp_path: Path) -> None:
    launch_dir = tmp_path / "LaunchAgents"
    config_path = tmp_path / ".env.properties"
    config_path.write_text("TUSHARE_TOKEN=file-token\nBARK_PUSH_URL=https://api.day.app/key\n", encoding="utf-8")
    _write_plist(launch_dir / "com.quant.api.plist", {"QUANT_HOME": "/tmp/quant"})
    _write_plist(launch_dir / "com.quant.scheduler.plist", {"QUANT_HOME": "/tmp/quant"})
    _write_plist(launch_dir / "com.quant.frontend.plist", {"QUANT_HOME": "/tmp/quant"})

    audit = build_environment_audit(
        env={"QUANT_HOME": "/tmp/quant"},
        launch_agents_dir=launch_dir,
        config_path=config_path,
    )

    names = {item["name"]: item for item in audit["checks"]}
    assert names["TUSHARE_TOKEN"]["status"] == "PASS"
    assert names["BARK_CHANNEL"]["status"] == "PASS"
    assert audit["secret_values_exposed"] is False
