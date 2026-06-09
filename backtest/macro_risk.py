"""
宏观事件风险提示模块

用于在策略提醒中识别非农、CPI、FOMC 等会影响利率预期的事件窗口。
这不是择时信号，只是对高波动风险做前置提醒。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List


@dataclass(frozen=True)
class MacroEvent:
    """重大宏观事件定义。"""

    event_date: date
    event_type: str
    name: str
    risk_level: str
    impact_note: str


class MacroRiskCalendar:
    """宏观风险日历。"""

    def __init__(self, events: List[MacroEvent]):
        self.events = sorted(events, key=lambda event: event.event_date)

    def events_near(self, current_date: date, days_before: int = 1, days_after: int = 1) -> List[MacroEvent]:
        """查询当前日期附近的重大事件。"""
        start = current_date - timedelta(days=days_after)
        end = current_date + timedelta(days=days_before)
        return [
            event for event in self.events
            if start <= event.event_date <= end
        ]


def build_default_macro_calendar() -> MacroRiskCalendar:
    """构建默认宏观事件日历，后续可替换为外部经济日历数据源。"""
    return MacroRiskCalendar(
        events=[
            MacroEvent(
                event_date=date(2026, 6, 5),
                event_type="NFP",
                name="美国5月非农就业报告",
                risk_level="HIGH",
                impact_note="就业过强会压低降息预期，推高美债收益率，冲击高估值科技链",
            ),
            MacroEvent(
                event_date=date(2026, 6, 10),
                event_type="CPI",
                name="美国5月CPI",
                risk_level="HIGH",
                impact_note="通胀超预期会压低降息预期，甚至引发加息担忧",
            ),
            MacroEvent(
                event_date=date(2026, 6, 17),
                event_type="FOMC",
                name="FOMC议息会议与新闻发布会",
                risk_level="HIGH",
                impact_note="利率决议、声明和点阵图会直接改变市场对降息/加息路径的定价",
            ),
        ]
    )


def format_macro_risk_warning(
    calendar: MacroRiskCalendar,
    current_date: date,
    days_before: int = 3,
    days_after: int = 1,
) -> str:
    """生成宏观风险提示文本。"""
    events = calendar.events_near(current_date, days_before=days_before, days_after=days_after)
    if not events:
        return ""

    lines = ["宏观风险提示:"]
    for event in events:
        distance = (event.event_date - current_date).days
        if distance > 0:
            timing = f"{distance}天后"
        elif distance == 0:
            timing = "今天"
        else:
            timing = f"{abs(distance)}天前"
        lines.append(f"- {timing}: {event.name}({event.risk_level})，{event.impact_note}")
    lines.append("操作原则: 事件窗口内不追高，不把单日回撤误判成趋势失效，必要时降低仓位或等待调仓日确认。")
    return "\n".join(lines)


def explain_macro_relationships() -> str:
    """解释非农、CPI、FOMC、降息和加息之间的关系。"""
    return (
        "非农看就业强弱，CPI看通胀高低，FOMC决定政策利率和表述未来路径。"
        "如果非农强、CPI高，市场会认为经济和通胀太热，美联储更难降息，甚至可能加息；"
        "美债收益率上行后，高估值成长股和AI硬件链会被杀估值。"
        "如果非农弱、CPI回落，市场更容易交易降息，成长股估值压力下降。"
        "所以这些事件不是直接决定股价，而是通过改变降息/加息预期影响资金风险偏好。"
    )
