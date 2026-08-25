"""
使用真实数据源的示例
演示如何从常见数据源加载A股数据

注意：需要先安装相应的数据源库
pip install akshare  # 或 tushare, baostock
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.data import DataManager
from backtest.strategies import MovingAverageCrossStrategy
from backtest.engine import BacktestEngine
from backtest.analysis import PerformanceAnalyzer


def load_data_from_akshare(symbol: str, start_date: str, end_date: str):
    """
    从AkShare加载数据
    
    安装: pip install akshare
    文档: https://github.com/akfamily/akshare
    """
    try:
        import akshare as ak
        import pandas as pd
        
        # 转换股票代码格式
        # AkShare使用: "000001" (不带后缀)
        symbol_code = symbol.split('.')[0]
        
        # 获取历史数据
        df = ak.stock_zh_a_hist(
            symbol=symbol_code,
            period="daily",
            start_date=start_date.replace('-', ''),
            end_date=end_date.replace('-', ''),
            adjust="qfq"  # 前复权
        )
        
        # 重命名列以匹配系统格式
        df = df.rename(columns={
            '日期': 'date',
            '开盘': 'open',
            '收盘': 'close',
            '最高': 'high',
            '最低': 'low',
            '成交量': 'volume'
        })
        
        # 选择需要的列
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        
        return df
        
    except ImportError:
        print("请先安装 akshare: pip install akshare")
        return None
    except Exception as e:
        print(f"加载数据失败: {e}")
        return None


def load_data_from_tushare(symbol: str, start_date: str, end_date: str, token: str):
    """
    从Tushare加载数据
    
    安装: pip install tushare
    文档: https://tushare.pro/
    
    需要注册账号获取token: https://tushare.pro/register
    """
    try:
        import tushare as ts
        import pandas as pd
        
        # 设置token
        ts.set_token(token)
        pro = ts.pro_api()
        
        # 转换日期格式
        start_date = start_date.replace('-', '')
        end_date = end_date.replace('-', '')
        
        # 获取历史数据
        df = pro.daily(
            ts_code=symbol,
            start_date=start_date,
            end_date=end_date
        )
        
        # 重命名列
        df = df.rename(columns={
            'trade_date': 'date',
            'vol': 'volume'
        })
        
        # 转换日期格式
        df['date'] = pd.to_datetime(df['date'])
        
        # 选择需要的列
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        
        # 排序（Tushare返回的数据是倒序的）
        df = df.sort_values('date')
        
        return df
        
    except ImportError:
        print("请先安装 tushare: pip install tushare")
        return None
    except Exception as e:
        print(f"加载数据失败: {e}")
        return None


def load_data_from_baostock(symbol: str, start_date: str, end_date: str):
    """
    从baostock加载数据
    
    安装: pip install baostock
    文档: http://baostock.com/
    """
    try:
        import baostock as bs
        import pandas as pd
        
        # 登陆系统
        lg = bs.login()
        
        # 获取历史数据
        rs = bs.query_history_k_data_plus(
            symbol,
            "date,open,high,low,close,volume",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2"  # 前复权
        )
        
        # 转换为DataFrame
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
        
        df = pd.DataFrame(data_list, columns=rs.fields)
        
        # 转换数据类型
        df['date'] = pd.to_datetime(df['date'])
        df['open'] = df['open'].astype(float)
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        df['volume'] = df['volume'].astype(float)
        
        # 登出系统
        bs.logout()
        
        return df
        
    except ImportError:
        print("请先安装 baostock: pip install baostock")
        return None
    except Exception as e:
        print(f"加载数据失败: {e}")
        return None


def main():
    """主函数"""
    print("=" * 60)
    print("使用真实数据源进行回测")
    print("=" * 60)
    
    # 配置
    symbol = '000001.SZ'  # 平安银行
    start_date = '2023-01-01'
    end_date = '2023-12-31'
    
    # 选择数据源（按优先级尝试）
    print("\n正在加载数据...")
    
    # 方法1: AkShare（推荐，免费无需注册）
    df = load_data_from_akshare(symbol, start_date, end_date)
    
    # 方法2: baostock（备选，免费无需注册）
    if df is None:
        print("尝试从 baostock 加载...")
        df = load_data_from_baostock(symbol, start_date, end_date)
    
    # 方法3: Tushare（需要注册获取token）
    if df is None:
        print("尝试从 Tushare 加载...")
        token = 'YOUR_TUSHARE_TOKEN'  # 替换为你的token
        df = load_data_from_tushare(symbol, start_date, end_date, token)
    
    if df is None or len(df) == 0:
        print("\n无法加载数据！")
        print("请确保：")
        print("1. 已安装数据源库 (pip install akshare/tushare/baostock)")
        print("2. 网络连接正常")
        print("3. 股票代码正确")
        return
    
    print(f"成功加载 {len(df)} 条数据")
    print(f"数据范围: {df['date'].min()} 到 {df['date'].max()}")
    print(f"\n数据预览:")
    print(df.head())
    
    # 创建数据管理器
    data_manager = DataManager()
    data_manager.load_data(symbol, df)
    
    # 创建策略
    strategy = MovingAverageCrossStrategy(symbol, short_window=5, long_window=20)
    
    # 创建回测引擎
    engine = BacktestEngine(
        data_manager=data_manager,
        strategy=strategy,
        initial_capital=1000000.0,
        commission_rate=0.0003,
        slippage=0.001
    )
    
    # 运行回测
    print("\n开始回测...")
    results = engine.run()
    
    # 分析结果
    analyzer = PerformanceAnalyzer(
        daily_values=results,
        trades=engine.trades,
        initial_capital=1000000.0
    )
    
    analyzer.print_summary()
    
    print("\n回测完成！")


if __name__ == '__main__':
    main()
