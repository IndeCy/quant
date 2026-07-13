from pathlib import Path

from runtime.config import get_config_value, load_properties_file


def test_load_properties_file_parses_kv_and_ignores_comments(tmp_path: Path) -> None:
    config_path = tmp_path / ".env.properties"
    config_path.write_text(
        """
# 本地私密配置，不提交 Git
TUSHARE_TOKEN=file-token
BARK_PUSH_URL = https://api.day.app/key
EMPTY_VALUE=
""".strip(),
        encoding="utf-8",
    )

    values = load_properties_file(config_path)

    assert values["TUSHARE_TOKEN"] == "file-token"
    assert values["BARK_PUSH_URL"] == "https://api.day.app/key"
    assert values["EMPTY_VALUE"] == ""


def test_get_config_value_prefers_properties_file_and_falls_back_to_env(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / ".env.properties"
    config_path.write_text("TUSHARE_TOKEN=file-token\n", encoding="utf-8")
    monkeypatch.setenv("TUSHARE_TOKEN", "env-token")
    monkeypatch.setenv("BARK_PUSH_URL", "env-bark")

    assert get_config_value("TUSHARE_TOKEN", config_path=config_path) == "file-token"
    assert get_config_value("BARK_PUSH_URL", config_path=config_path) == "env-bark"
