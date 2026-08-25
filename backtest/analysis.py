"""
绩效分析模块 (Performance Analysis Module)
计算和分析回测结果的各项指标
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class PerformanceAnalyzer:
    """绩效分析器"""
    
    def __init__(self, daily_values: pd.DataFrame, trades: list, 
                 initial_capital: float, risk_free_rate: float = 0.03):
        """
        初始化绩效分析器
        
        Args:
            daily_values: 每日资产价值DataFrame
            trades: 交易记录列表
            initial_capital: 初始资金
            risk_free_rate: 无风险收益率（年化）
        """
        self.daily_values = daily_values
        self.trades = pd.DataFrame(trades) if trades else pd.DataFrame()
        self.initial_capital = initial_capital
        self.risk_free_rate = risk_free_rate
        
        self._calculate_metrics()
    
    def _calculate_metrics(self):
        """计算各项绩效指标"""
        if len(self.daily_values) == 0:
            return
        
        # 计算每日收益率
        self.daily_values['returns'] = self.daily_values['total_value'].pct_change()
        self.daily_values['cumulative_returns'] = (
            (1 + self.daily_values['returns']).cumprod() - 1
        )
        
    def get_total_return(self) -> float:
        """计算总收益率"""
        if len(self.daily_values) == 0:
            return 0.0
        final_value = self.daily_values['total_value'].iloc[-1]
        return (final_value - self.initial_capital) / self.initial_capital
    
    def get_annualized_return(self) -> float:
        """计算年化收益率"""
        if len(self.daily_values) < 2:
            return 0.0
        
        total_return = self.get_total_return()
        days = len(self.daily_values)
        years = days / 252  # 假设一年252个交易日
        
        if years == 0:
            return 0.0
        
        return (1 + total_return) ** (1 / years) - 1
    
    def get_sharpe_ratio(self) -> float:
        """计算夏普比率"""
        if len(self.daily_values) < 2:
            return 0.0
        
        returns = self.daily_values['returns'].dropna()
        if returns.empty or np.isclose(returns.std(), 0.0):
            return 0.0

        excess_returns = returns - self.risk_free_rate / 252
        excess_std = excess_returns.std()
        
        # 极小标准差通常来自浮点误差，直接计算会把夏普比率放大成异常值。
        if np.isclose(excess_std, 0.0):
            return 0.0
        
        return np.sqrt(252) * excess_returns.mean() / excess_std
    
    def get_max_drawdown(self) -> float:
        """计算最大回撤"""
        if len(self.daily_values) == 0:
            return 0.0
        
        cumulative = self.daily_values['total_value']
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        
        return drawdown.min()
    
    def get_win_rate(self) -> float:
        """计算胜率"""
        if len(self.trades) == 0:
            return 0.0
        
        # 需要配对买卖来计算盈亏
        # 这里简化处理，基于每日收益
        if len(self.daily_values) < 2:
            return 0.0
        
        positive_days = (self.daily_values['returns'] > 0).sum()
        total_days = len(self.daily_values) - 1  # 第一天没有收益
        
        return positive_days / total_days if total_days > 0 else 0.0
    
    def get_volatility(self) -> float:
        """计算波动率（年化）"""
        if len(self.daily_values) < 2:
            return 0.0
        
        return self.daily_values['returns'].std() * np.sqrt(252)

    def get_turnover_rate(self) -> float:
        """计算区间换手率，使用成交金额除以平均资产规模。"""
        if self.trades.empty or len(self.daily_values) == 0:
            return 0.0
        traded_value = (self.trades["quantity"].abs() * self.trades["price"]).sum()
        average_asset = self.daily_values["total_value"].mean()
        if average_asset == 0:
            return 0.0
        return float(traded_value / average_asset)

    def get_total_transaction_cost(self) -> float:
        """计算总交易成本，优先使用成交模型输出的 total_fee。"""
        if self.trades.empty:
            return 0.0
        if "total_fee" in self.trades.columns:
            return float(self.trades["total_fee"].sum())
        if "commission" in self.trades.columns:
            return float(self.trades["commission"].sum())
        return 0.0

    def get_failed_trade_count(self) -> int:
        """获取成交失败次数，来自回测每日记录。"""
        if "failed_trade_count" not in self.daily_values.columns or len(self.daily_values) == 0:
            return 0
        return int(self.daily_values["failed_trade_count"].max())
    
    def get_summary(self) -> Dict[str, float]:
        """获取绩效摘要"""
        return {
            '总收益率': self.get_total_return(),
            '年化收益率': self.get_annualized_return(),
            '夏普比率': self.get_sharpe_ratio(),
            '最大回撤': self.get_max_drawdown(),
            '胜率': self.get_win_rate(),
            '波动率': self.get_volatility(),
            '换手率': self.get_turnover_rate(),
            '总交易成本': self.get_total_transaction_cost(),
            '成交失败次数': self.get_failed_trade_count(),
            '交易次数': len(self.trades),
            '最终资产': self.daily_values['total_value'].iloc[-1] if len(self.daily_values) > 0 else self.initial_capital
        }
    
    def print_summary(self):
        """打印绩效摘要"""
        print("\n" + "=" * 50)
        print("回测绩效报告")
        print("=" * 50)
        
        summary = self.get_summary()
        
        print(f"初始资金: CNY {self.initial_capital:,.2f}")
        print(f"最终资产: CNY {summary['最终资产']:,.2f}")
        print(f"总收益率: {summary['总收益率']:.2%}")
        print(f"年化收益率: {summary['年化收益率']:.2%}")
        print(f"夏普比率: {summary['夏普比率']:.2f}")
        print(f"最大回撤: {summary['最大回撤']:.2%}")
        print(f"波动率(年化): {summary['波动率']:.2%}")
        print(f"换手率: {summary['换手率']:.2%}")
        print(f"总交易成本: CNY {summary['总交易成本']:,.2f}")
        print(f"成交失败次数: {int(summary['成交失败次数'])}")
        print(f"胜率: {summary['胜率']:.2%}")
        print(f"交易次数: {int(summary['交易次数'])}")
        print("=" * 50 + "\n")
    
    def plot_equity_curve(self, save_path: Optional[str] = None):
        """
        绘制资金曲线
        
        Args:
            save_path: 保存路径（可选）
        """
        if len(self.daily_values) == 0:
            print("没有数据可绘制")
            return

        # 绘图功能才需要 matplotlib，避免只做绩效计算时强依赖绘图库。
        import matplotlib.pyplot as plt
        
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
        
        # 资金曲线
        ax1.plot(self.daily_values.index, self.daily_values['total_value'], 
                label='总资产', linewidth=2)
        ax1.axhline(y=self.initial_capital, color='r', linestyle='--', 
                   label='初始资金', alpha=0.5)
        ax1.set_ylabel('资产价值 (CNY)', fontsize=12)
        ax1.set_title('资金曲线', fontsize=14, fontweight='bold')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 回撤曲线
        cumulative = self.daily_values['total_value']
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        
        ax2.fill_between(self.daily_values.index, drawdown, 0, 
                        alpha=0.3, color='red', label='回撤')
        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_ylabel('回撤', fontsize=12)
        ax2.set_title('回撤曲线', fontsize=14, fontweight='bold')
        ax2.legend()
        ax2.grid(True, alpha=0.3)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"图表已保存至: {save_path}")
        else:
            plt.show()
