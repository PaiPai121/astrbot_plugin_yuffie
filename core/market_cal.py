"""
market_cal.py - 交易日历管理模块

职责:
    1. 使用 pandas_market_calendars 接入 CME（芝加哥商品交易所）日历
    2. 判断当前是否处于休市状态
    3. 判断当前是否处于开盘静默期（开盘前/后 30 分钟内），过滤跳空假信号

设计原则:
    - 准确性：使用权威的交易所日历数据
    - 时区感知：正确处理 CME 时区（America/Chicago）与 UTC/本地时间的转换
    - 可配置：静默期时长从 config.yaml 读取
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pytz

# 尝试导入 pandas_market_calendars，如果未安装则提供降级方案
try:
    import pandas_market_calendars as mcal
    from pandas import Timestamp
    MARKET_CALENDARS_AVAILABLE = True
except ImportError:
    MARKET_CALENDARS_AVAILABLE = False
    print("[MarketCal] 警告：pandas_market_calendars 未安装，将使用降级模式")

# 尝试导入 pandas 用于时间处理
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("[MarketCal] 警告：pandas 未安装，部分功能可能受限")


# 获取当前文件所在目录，用于定位配置文件
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def load_config() -> dict:
    """
    加载配置文件 config.yaml
    
    Returns:
        dict: 配置字典，如果加载失败则返回默认配置
    """
    default_config = {
        "monitor": {
            "cooldown_minutes": 30
        },
        "calendar": {
            "exchange": "CME",
            "open_mute_minutes": 30
        }
    }
    
    try:
        # 尝试使用 PyYAML 加载配置
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config:
                return config
    except FileNotFoundError:
        print(f"[MarketCal] 配置文件未找到：{CONFIG_PATH}，使用默认配置")
    except ImportError:
        print("[MarketCal] PyYAML 未安装，使用默认配置")
    except Exception as e:
        print(f"[MarketCal] 加载配置文件失败：{e}，使用默认配置")
    
    return default_config


class MarketCalendar:
    """
    市场日历管理器 - 管理交易时间和静默期
    
    核心功能:
        1. is_market_closed() -> bool: 判断当前是否休市
        2. is_opening_silent_period() -> bool: 判断是否处于开盘静默期
        3. get_next_market_open() -> datetime: 获取下次开盘时间
        4. get_next_market_close() -> datetime: 获取下次收盘时间
    
    支持的交易所:
        - CME: 芝加哥商品交易所（默认，用于黄金/期金交易）
        - NYSE: 纽约证券交易所
        - NASDAQ: 纳斯达克
    """
    
    # CME 时区：美国中部时间（Chicago）
    CME_TIMEZONE = pytz.timezone("America/Chicago")
    
    def __init__(
        self, 
        exchange: str = "CME",
        open_mute_minutes: Optional[int] = None
    ):
        """
        初始化市场日历
        
        Args:
            exchange: 交易所代码（默认 "CME"）
            open_mute_minutes: 开盘静默期时长（分钟），从 config.yaml 读取
        
        配置加载逻辑:
            1. 优先使用传入的参数
            2. 如果未传入，则从 config.yaml 读取
            3. 如果配置文件也不存在，使用默认值 30 分钟
        """
        self.exchange = exchange.upper()
        
        # 加载配置文件获取静默期设置
        config = load_config()
        
        # 优先使用传入参数，否则从配置读取，最后使用默认值
        if open_mute_minutes is not None:
            self.open_mute_minutes = open_mute_minutes
        else:
            self.open_mute_minutes = config.get("calendar", {}).get(
                "open_mute_minutes", 30
            )
        
        print(f"[MarketCal] 初始化：交易所={self.exchange}, 静默期={self.open_mute_minutes}分钟")
        
        # 初始化交易所日历
        self._calendar = self._init_calendar()
    
    def _init_calendar(self):
        """
        初始化交易所日历对象

        Returns:
            交易所日历实例，如果初始化失败则返回 None

        注意:
            pandas_market_calendars 5.x 版本中，CME 需要指定具体产品线:
            - CME_Equity: CME 股票期货
            - CMEGlobex_Gold (GC): 黄金期货
            - CBOT_Equity: CBOT 股票
            我们使用 "CME_Equity" 作为默认，或使用 "us_futures" 作为通用期货日历
        """
        if not MARKET_CALENDARS_AVAILABLE:
            print("[MarketCal] 使用降级模式（无 pandas_market_calendars）")
            return None

        # 可用的 CME 相关日历（根据 pandas_market_calendars 5.x）
        CME_CALENDARS = [
            "CME_Equity",       # CME 股票期货
            "CBOT_Equity",      # CBOT 股票期货
            "CMEGlobex_Gold",   # 黄金期货 (GC)
            "CMEGlobex_EnergyAndMetals",  # 能源和金属
            "us_futures",       # 美国期货通用日历
            "CME_Bond",         # CME 债券
            "CBOT_Agriculture", # CBOT 农产品
        ]

        try:
            # 根据交易所代码获取对应的日历
            if self.exchange == "CME":
                # 尝试多个 CME 日历名称
                for calendar_name in CME_CALENDARS:
                    try:
                        calendar = mcal.get_calendar(calendar_name)
                        print(f"[MarketCal] 使用日历：{calendar_name}")
                        break
                    except KeyError:
                        continue
                else:
                    # 如果所有 CME 日历都失败，尝试 NYSE 作为后备
                    print("[MarketCal] CME 日历不可用，尝试使用 NYSE 日历")
                    calendar = mcal.get_calendar("NYSE")
            elif self.exchange == "NYSE":
                # 纽交所日历
                calendar = mcal.get_calendar("NYSE")
            elif self.exchange == "NASDAQ":
                # 纳斯达克日历
                calendar = mcal.get_calendar("NASDAQ")
            else:
                # 默认使用 NYSE（美股）
                print(f"[MarketCal] 未知交易所 '{self.exchange}'，使用 NYSE 默认日历")
                calendar = mcal.get_calendar("NYSE")

            print(f"[MarketCal] 成功加载 {self.exchange} 日历")
            return calendar

        except Exception as e:
            print(f"[MarketCal] 加载交易所日历失败：{e}，将使用降级模式")
            return None
    
    def _get_current_cme_time(self) -> datetime:
        """
        获取当前 CME 时区（美国中部时间）的时间
        
        Returns:
            datetime: 当前 CME 时区的时间
        """
        return datetime.now(self.CME_TIMEZONE)
    
    def _is_weekend(self, dt: Optional[datetime] = None) -> bool:
        """
        判断指定时间是否为周末
        
        Args:
            dt: 要判断的时间，如果为 None 则使用当前时间
        
        Returns:
            bool: True 表示是周末
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        # weekday() 返回 0-6，其中 5=周六，6=周日
        return dt.weekday() >= 5
    
    def is_market_closed(self, dt: Optional[datetime] = None) -> bool:
        """
        判断市场是否处于休市状态
        
        休市条件:
            1. 周末（周六或周日）
            2. 美国法定节假日（如感恩节、圣诞节等）
            3. 非交易时段（盘前或盘后）
        
        Args:
            dt: 要判断的时间，如果为 None 则使用当前时间
        
        Returns:
            bool: True 表示市场已休市
        
        降级处理:
            - 如果 pandas_market_calendars 不可用，仅判断周末
            - 确保系统在任何情况下都能正常运行
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        # 确保时间是 CME 时区
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        # 条件 1: 判断是否为周末
        if self._is_weekend(dt):
            print(f"[MarketCal] 当前是周末，市场休市")
            return True
        
        # 条件 2 & 3: 使用日历判断节假日和非交易时段
        if self._calendar is not None and PANDAS_AVAILABLE:
            try:
                # 获取当天的交易时间表
                date_str = dt.strftime("%Y-%m-%d")
                # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
                schedule = self._calendar.schedule(
                    start_date=pd.Timestamp(date_str),
                    end_date=pd.Timestamp(date_str)
                )
                
                # 检查当天是否为交易日（节假日会返回空表）
                if schedule.empty:
                    print(f"[MarketCal] 今天是节假日，市场休市 ({date_str})")
                    return True
                
                # 检查当前时间是否在交易时段内
                market_open = schedule.loc[date_str, "market_open"]
                market_close = schedule.loc[date_str, "market_close"]
                
                # 转换为 CME 时区进行比较
                if hasattr(market_open, 'tz'):
                    market_open = market_open.tz_convert(self.CME_TIMEZONE)
                else:
                    market_open = self.CME_TIMEZONE.localize(market_open)
                
                if hasattr(market_close, 'tz'):
                    market_close = market_close.tz_convert(self.CME_TIMEZONE)
                else:
                    market_close = self.CME_TIMEZONE.localize(market_close)
                
                # 判断当前时间是否在交易时段外
                if dt < market_open or dt > market_close:
                    print(f"[MarketCal] 当前时间 {dt.strftime('%H:%M')} 不在交易时段 "
                          f"({market_open.strftime('%H:%M')} - {market_close.strftime('%H:%M')})")
                    return True
                
                # 在交易时段内
                return False
                
            except Exception as e:
                print(f"[MarketCal] 判断交易时段异常：{e}，降级为周末判断")
                # 降级处理：仅判断周末
                return self._is_weekend(dt)
        else:
            # 降级模式：仅判断周末
            print("[MarketCal] 降级模式：仅判断周末")
            return self._is_weekend(dt)
    
    def is_opening_silent_period(self, dt: Optional[datetime] = None) -> bool:
        """
        判断是否处于开盘静默期
        
        静默期定义:
            - 开盘前 open_mute_minutes 分钟
            - 开盘后 open_mute_minutes 分钟
        
        设计目的:
            - 过滤周一开盘跳空缺口导致的假信号
            - 避免 ATR 在开盘初期因数据不足而失真
        
        Args:
            dt: 要判断的时间，如果为 None 则使用当前时间
        
        Returns:
            bool: True 表示处于静默期，应暂停动态 ATR 监控
        
        注意:
            - 如果市场休市，直接返回 False（休市时不需要判断静默期）
            - 静默期只在交易日有效
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        # 确保时间是 CME 时区
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        # 如果市场休市，直接返回 False
        if self.is_market_closed(dt):
            return False
        
        if self._calendar is None or not PANDAS_AVAILABLE:
            # 降级模式：无法精确判断开盘时间，保守返回 False
            print("[MarketCal] 降级模式：无法判断静默期，默认不静默")
            return False
        
        try:
            date_str = dt.strftime("%Y-%m-%d")
            # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
            schedule = self._calendar.schedule(
                start_date=pd.Timestamp(date_str),
                end_date=pd.Timestamp(date_str)
            )
            
            if schedule.empty:
                # 节假日不会有静默期
                return False
            
            market_open = schedule.loc[date_str, "market_open"]
            
            # 转换为 CME 时区
            if hasattr(market_open, 'tz'):
                market_open = market_open.tz_convert(self.CME_TIMEZONE)
            else:
                market_open = self.CME_TIMEZONE.localize(market_open)
            
            # 计算静默期边界
            silent_start = market_open - timedelta(minutes=self.open_mute_minutes)
            silent_end = market_open + timedelta(minutes=self.open_mute_minutes)
            
            # 判断当前时间是否在静默期内
            in_silent_period = silent_start <= dt <= silent_end
            
            if in_silent_period:
                if dt < market_open:
                    remaining = (market_open - dt).seconds // 60
                    print(f"[MarketCal] 开盘前静默期，距离开盘还有 {remaining} 分钟")
                else:
                    elapsed = (dt - market_open).seconds // 60
                    print(f"[MarketCal] 开盘后静默期，已开盘 {elapsed} 分钟")
            
            return in_silent_period
            
        except Exception as e:
            print(f"[MarketCal] 判断静默期异常：{e}，默认不静默")
            return False
    
    def get_next_market_open(self, dt: Optional[datetime] = None) -> Optional[datetime]:
        """
        获取下次市场开盘时间
        
        Args:
            dt: 参考时间，如果为 None 则使用当前时间
        
        Returns:
            datetime: 下次开盘时间，如果无法获取则返回 None
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        if self._calendar is None or not PANDAS_AVAILABLE:
            print("[MarketCal] 无法获取开盘时间（降级模式）")
            return None
        
        try:
            # 从当前时间开始，查找未来 7 天的交易日程
            start_date = dt.strftime("%Y-%m-%d")
            end_date = (dt + timedelta(days=7)).strftime("%Y-%m-%d")

            # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
            schedule = self._calendar.schedule(
                start_date=pd.Timestamp(start_date),
                end_date=pd.Timestamp(end_date)
            )
            
            if schedule.empty:
                print("[MarketCal] 未来 7 天无交易日程")
                return None
            
            # 找到第一个未来的开盘时间
            for date, row in schedule.iterrows():
                market_open = row["market_open"]
                
                if hasattr(market_open, 'tz'):
                    market_open = market_open.tz_convert(self.CME_TIMEZONE)
                else:
                    market_open = self.CME_TIMEZONE.localize(market_open)
                
                if market_open > dt:
                    return market_open
            
            return None
            
        except Exception as e:
            print(f"[MarketCal] 获取开盘时间失败：{e}")
            return None
    
    def get_next_market_close(self, dt: Optional[datetime] = None) -> Optional[datetime]:
        """
        获取下次市场收盘时间
        
        Args:
            dt: 参考时间，如果为 None 则使用当前时间
        
        Returns:
            datetime: 下次收盘时间，如果无法获取则返回 None
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        if self._calendar is None or not PANDAS_AVAILABLE:
            print("[MarketCal] 无法获取收盘时间（降级模式）")
            return None
        
        try:
            start_date = dt.strftime("%Y-%m-%d")
            end_date = (dt + timedelta(days=7)).strftime("%Y-%m-%d")

            # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
            schedule = self._calendar.schedule(
                start_date=pd.Timestamp(start_date),
                end_date=pd.Timestamp(end_date)
            )
            
            if schedule.empty:
                print("[MarketCal] 未来 7 天无交易日程")
                return None
            
            # 找到第一个未来的收盘时间
            for date, row in schedule.iterrows():
                market_close = row["market_close"]
                
                if hasattr(market_close, 'tz'):
                    market_close = market_close.tz_convert(self.CME_TIMEZONE)
                else:
                    market_close = self.CME_TIMEZONE.localize(market_close)
                
                if market_close > dt:
                    return market_close
            
            return None
            
        except Exception as e:
            print(f"[MarketCal] 获取收盘时间失败：{e}")
            return None
    
    def get_trading_hours(self, dt: Optional[datetime] = None) -> Optional[Tuple[datetime, datetime]]:
        """
        获取指定日期的交易时段
        
        Args:
            dt: 指定日期，如果为 None 则使用当前日期
        
        Returns:
            Tuple[datetime, datetime]: (开盘时间，收盘时间)，如果不是交易日则返回 None
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        if self._calendar is None or not PANDAS_AVAILABLE:
            return None
        
        try:
            date_str = dt.strftime("%Y-%m-%d")
            # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
            schedule = self._calendar.schedule(
                start_date=pd.Timestamp(date_str),
                end_date=pd.Timestamp(date_str)
            )
            
            if schedule.empty:
                return None
            
            market_open = schedule.loc[date_str, "market_open"]
            market_close = schedule.loc[date_str, "market_close"]
            
            # 转换为 CME 时区
            if hasattr(market_open, 'tz'):
                market_open = market_open.tz_convert(self.CME_TIMEZONE)
                market_close = market_close.tz_convert(self.CME_TIMEZONE)
            else:
                market_open = self.CME_TIMEZONE.localize(market_open)
                market_close = self.CME_TIMEZONE.localize(market_close)
            
            return (market_open, market_close)
            
        except Exception as e:
            print(f"[MarketCal] 获取交易时段失败：{e}")
            return None
    
    def is_valid_trading_day(self, dt: Optional[datetime] = None) -> bool:
        """
        判断指定日期是否为有效的交易日
        
        Args:
            dt: 指定日期，如果为 None 则使用当前日期
        
        Returns:
            bool: True 表示是交易日
        """
        if dt is None:
            dt = self._get_current_cme_time()
        
        if dt.tzinfo is None:
            dt = self.CME_TIMEZONE.localize(dt)
        else:
            dt = dt.astimezone(self.CME_TIMEZONE)
        
        # 周末不是交易日
        if self._is_weekend(dt):
            return False
        
        if self._calendar is None or not PANDAS_AVAILABLE:
            # 降级模式：假设非周末都是交易日
            return True
        
        try:
            date_str = dt.strftime("%Y-%m-%d")
            # pandas_market_calendars 5.x API: 使用 start_date 和 end_date
            schedule = self._calendar.schedule(
                start_date=pd.Timestamp(date_str),
                end_date=pd.Timestamp(date_str)
            )
            
            return not schedule.empty
            
        except Exception as e:
            print(f"[MarketCal] 判断交易日失败：{e}")
            return True  # 保守返回 True，避免误判


# ==================== 使用示例 ====================
if __name__ == "__main__":
    # 测试代码
    print("=== 测试 MarketCalendar ===\n")
    
    # 初始化日历（会自动从 config.yaml 读取配置）
    cal = MarketCalendar()
    
    # 获取当前 CME 时间
    now_cme = cal._get_current_cme_time()
    print(f"当前 CME 时间：{now_cme.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    # 测试休市判断
    print(f"\n当前是否休市：{cal.is_market_closed()}")
    
    # 测试静默期判断
    print(f"当前是否静默期：{cal.is_opening_silent_period()}")
    
    # 获取下次开盘/收盘时间
    next_open = cal.get_next_market_open()
    next_close = cal.get_next_market_close()
    
    if next_open:
        print(f"下次开盘时间：{next_open.strftime('%Y-%m-%d %H:%M:%S')}")
    if next_close:
        print(f"下次收盘时间：{next_close.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试指定日期（周末）
    weekend = datetime(2026, 3, 1, 10, 0)  # 周日
    print(f"\n2026-03-01 (周日) 是否休市：{cal.is_market_closed(weekend)}")
    
    # 测试指定日期（工作日）
    weekday = datetime(2026, 3, 2, 10, 0)  # 周一
    print(f"2026-03-02 (周一) 是否休市：{cal.is_market_closed(weekday)}")
    print(f"2026-03-02 (周一) 是否静默期：{cal.is_opening_silent_period(weekday)}")
