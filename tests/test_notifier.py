"""
测试系统通知模块
"""

from backtest.notifier import BarkNotifier, NotificationMessage, build_notifier


def test_bark_notifier_builds_encoded_url():
    """Bark 通知器应对中文标题和正文做 URL 编码。"""
    notifier = BarkNotifier("https://api.day.app/key")
    message = NotificationMessage(title="主线链动策略", body="今日无需调仓")

    url = notifier.build_url(message)

    assert url == "https://api.day.app/key/%E4%B8%BB%E7%BA%BF%E9%93%BE%E5%8A%A8%E7%AD%96%E7%95%A5/%E4%BB%8A%E6%97%A5%E6%97%A0%E9%9C%80%E8%B0%83%E4%BB%93"


def test_build_notifier_returns_bark_notifier():
    """通知工厂应按 provider 创建 Bark 通知器。"""
    notifier = build_notifier(provider="bark", endpoint="https://api.day.app/key")

    assert isinstance(notifier, BarkNotifier)


def test_build_notifier_rejects_unknown_provider():
    """未知通知渠道应明确报错，避免静默丢通知。"""
    try:
        build_notifier(provider="sms", endpoint="x")
    except ValueError as exc:
        assert "暂不支持" in str(exc)
    else:
        raise AssertionError("未知 provider 应抛出 ValueError")
