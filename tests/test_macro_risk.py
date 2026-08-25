"""
测试宏观事件风险提示模块
"""

from datetime import date

from backtest.macro_risk import (
    MacroEvent,
    MacroRiskCalendar,
    explain_macro_relationships,
    format_macro_risk_warning,
)


def test_calendar_finds_upcoming_high_risk_event():
    """事件前窗口内应提示即将发布的高风险宏观数据。"""
    calendar = MacroRiskCalendar(
        events=[
            MacroEvent(
                event_date=date(2026, 6, 10),
                event_type="CPI",
                name="美国5月CPI",
                risk_level="HIGH",
                impact_note="通胀超预期会推高利率预期，压制AI成长股估值",
            )
        ]
    )

    events = calendar.events_near(date(2026, 6, 9), days_before=2, days_after=1)

    assert len(events) == 1
    assert events[0].event_type == "CPI"


def test_format_macro_risk_warning_contains_action_hint():
    """宏观风险提示应包含事件名和操作建议。"""
    calendar = MacroRiskCalendar(
        events=[
            MacroEvent(
                event_date=date(2026, 6, 17),
                event_type="FOMC",
                name="FOMC议息会议",
                risk_level="HIGH",
                impact_note="议息声明和点阵图会改变降息/加息预期",
            )
        ]
    )

    warning = format_macro_risk_warning(calendar, date(2026, 6, 16))

    assert "FOMC议息会议" in warning
    assert "不追高" in warning


def test_default_warning_starts_three_days_before_event():
    """默认风险窗口应提前三天提醒，覆盖周末到下周数据发布的情形。"""
    calendar = MacroRiskCalendar(
        events=[
            MacroEvent(
                event_date=date(2026, 6, 10),
                event_type="CPI",
                name="美国5月CPI",
                risk_level="HIGH",
                impact_note="通胀数据会影响利率预期",
            )
        ]
    )

    warning = format_macro_risk_warning(calendar, date(2026, 6, 7))

    assert "3天后" in warning


def test_explain_macro_relationships_mentions_rate_path():
    """宏观解释应说清数据、降息加息和成长股估值的关系。"""
    text = explain_macro_relationships()

    assert "非农" in text
    assert "CPI" in text
    assert "降息" in text
    assert "加息" in text
