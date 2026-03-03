"""
indicators.py - 量化计算引擎

职责:
    1. 计算动态 ATR（真实波动幅度）指标
    2. 实现异常波动检测（基于 ATR 阈值）
    3. 提供多因子分析的基础计算功能

设计原则:
    - 准确性：使用标准量化公式计算
    - 高效性：基于 pandas/pandas_ta 向量化运算
    - 可配置：阈值参数从 config.yaml 读取
    - 降级保护：ATR 失效时使用绝对值阈值
"""

import os
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple, Union
import time

# 尝试导入 pandas
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("[Indicators] 警告：pandas 未安装，将使用纯 Python 降级模式")

# 尝试导入 pandas_ta
try:
    import pandas_ta as ta
    PANDAS_TA_AVAILABLE = True
except ImportError:
    PANDAS_TA_AVAILABLE = False
    print("[Indicators] 提示：pandas_ta 未安装，将使用内置 ATR 计算")

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


# ==================== 数据模型 ====================

@dataclass
class VolatilitySignal:
    """
    波动率信号 - 异常波动检测结果
    
    Attributes:
        triggered: 是否触发异常波动信号
        current_price: 当前价格
        reference_price: 参考价格（滑窗期初价格）
        price_change: 价格变化绝对值
        price_change_pct: 价格变化百分比
        atr_value: ATR 值
        threshold: 触发阈值
        signal_type: 信号类型（'up' 上涨，'down' 下跌，'none' 无信号）
        timestamp: 时间戳
    """
    triggered: bool
    current_price: float
    reference_price: float
    price_change: float
    price_change_pct: float
    atr_value: Optional[float]
    threshold: float
    signal_type: str  # 'up', 'down', 'none'
    timestamp: float = 0.0
    
    def __post_init__(self):
        """后处理：设置时间戳和信号类型"""
        if self.timestamp == 0.0:
            self.timestamp = time.time()
        
        if not self.triggered:
            self.signal_type = 'none'
        elif self.price_change > 0:
            self.signal_type = 'up'
        else:
            self.signal_type = 'down'
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "triggered": self.triggered,
            "current_price": self.current_price,
            "reference_price": self.reference_price,
            "price_change": self.price_change,
            "price_change_pct": self.price_change_pct,
            "atr_value": self.atr_value,
            "threshold": self.threshold,
            "signal_type": self.signal_type,
            "timestamp": self.timestamp
        }
    
    def __str__(self) -> str:
        """字符串表示"""
        if not self.triggered:
            return f"VolatilitySignal(无信号，价格={self.current_price})"
        
        direction = "上涨" if self.signal_type == 'up' else "下跌"
        return (f"VolatilitySignal(异常{direction}! 价格={self.current_price}, "
                f"变化={self.price_change:.2f} ({self.price_change_pct:.2f}%), "
                f"阈值={self.threshold:.2f})")


@dataclass
class OHLCV:
    """
    OHLCV 数据模型 - 用于 ATR 计算
    
    Attributes:
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        volume: 成交量
        timestamp: 时间戳
    """
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timestamp: float = 0.0
    
    @classmethod
    def from_tick(cls, price: float, timestamp: float = None) -> 'OHLCV':
        """
        从 Tick 价格创建 OHLCV（简化版，OHLC 相同）
        
        Args:
            price: 价格
            timestamp: 时间戳
        
        Returns:
            OHLCV 实例
        """
        return cls(
            open=price,
            high=price,
            low=price,
            close=price,
            timestamp=timestamp or time.time()
        )


# ==================== 配置加载 ====================

def load_config() -> dict:
    """
    加载配置文件 config.yaml
    
    Returns:
        dict: 配置字典
    """
    default_config = {
        "atr_strategy": {
            "enabled": True,
            "period": 14,
            "k_multiplier": 2.5,
            "fallback_threshold": 10.0,
            "volume_surge_ratio": 1.5
        }
    }
    
    try:
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config:
                return config
    except Exception as e:
        print(f"[Indicators] 加载配置文件失败：{e}，使用默认配置")
    
    return default_config


# ==================== ATR 计算引擎 ====================

def calculate_atr(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int = 14,
    use_pandas_ta: bool = True
) -> Optional[float]:
    """
    计算 ATR（真实波动幅度）指标
    
    ATR（Average True Range）是衡量价格波动性的技术指标，
    由 J. Welles Wilder 提出，用于评估市场的波动程度。
    
    计算公式:
        True Range = max(High - Low, |High - Close_prev|, |Low - Close_prev|)
        ATR = SMA(True Range, period)
    
    Args:
        high: 最高价列表（按时间正序）
        low: 最低价列表
        close: 收盘价列表
        period: ATR 计算周期（默认 14）
        use_pandas_ta: 是否使用 pandas_ta 库（如果可用）
    
    Returns:
        float: 最新 ATR 值，如果数据不足返回 None
    
    示例:
        >>> high = [2660, 2665, 2670, ...]
        >>> low = [2650, 2655, 2660, ...]
        >>> close = [2655, 2660, 2665, ...]
        >>> atr = calculate_atr(high, low, close, period=14)
    """
    # 数据验证
    if not high or not low or not close:
        print("[Indicators] ATR 计算失败：数据为空")
        return None
    
    if len(high) < period + 1:
        print(f"[Indicators] ATR 计算失败：数据量不足（需要至少 {period + 1} 条，实际 {len(high)} 条）")
        return None
    
    if len(high) != len(low) or len(high) != len(close):
        print("[Indicators] ATR 计算失败：数据长度不一致")
        return None
    
    # 尝试使用 pandas_ta
    if PANDAS_AVAILABLE and use_pandas_ta:
        try:
            if PANDAS_TA_AVAILABLE:
                return _calculate_atr_pandas_ta(high, low, close, period)
            else:
                return _calculate_atr_pandas(high, low, close, period)
        except Exception as e:
            print(f"[Indicators] pandas ATR 计算失败：{e}，降级到纯 Python")
    
    # 降级到纯 Python 实现
    return _calculate_atr_pure_python(high, low, close, period)


def _calculate_atr_pandas_ta(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int
) -> Optional[float]:
    """使用 pandas_ta 计算 ATR"""
    df = pd.DataFrame({
        'high': high,
        'low': low,
        'close': close
    })
    
    # 使用 pandas_ta 计算 ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'], length=period)
    
    # 返回最后一个有效的 ATR 值
    atr_value = df['atr'].iloc[-1]
    
    if pd.isna(atr_value):
        return None
    
    return float(atr_value)


def _calculate_atr_pandas(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int
) -> Optional[float]:
    """使用 pandas（无 pandas_ta）计算 ATR"""
    df = pd.DataFrame({
        'high': high,
        'low': low,
        'close': close
    })
    
    # 计算 True Range
    df['prev_close'] = df['close'].shift(1)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['prev_close'])
    df['tr3'] = abs(df['low'] - df['prev_close'])
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    
    # 计算 ATR（简单移动平均）
    df['atr'] = df['tr'].rolling(window=period).mean()
    
    atr_value = df['atr'].iloc[-1]
    
    if pd.isna(atr_value):
        return None
    
    return float(atr_value)


def _calculate_atr_pure_python(
    high: List[float],
    low: List[float],
    close: List[float],
    period: int
) -> Optional[float]:
    """
    纯 Python 实现 ATR 计算（降级模式）
    
    使用 Wilder 的平滑方法（指数移动平均）
    """
    n = len(close)
    
    if n < period + 1:
        return None
    
    # 计算 True Range
    true_ranges = []
    for i in range(1, n):
        tr1 = high[i] - low[i]
        tr2 = abs(high[i] - close[i - 1])
        tr3 = abs(low[i] - close[i - 1])
        tr = max(tr1, tr2, tr3)
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return None
    
    # 第一个 ATR = 简单平均
    atr = sum(true_ranges[:period]) / period
    
    # Wilder 平滑：ATR_new = (ATR_prev * (period - 1) + TR_current) / period
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    
    return atr


def calculate_atr_from_ticks(
    prices: List[float],
    period: int = 14
) -> Optional[float]:
    """
    从 Tick 价格列表计算 ATR（简化版）
    
    当只有 Tick 价格（无 OHLCV）时使用，假设 OHLC 相同
    
    Args:
        prices: 价格列表（按时间正序）
        period: ATR 周期
    
    Returns:
        float: ATR 值
    """
    if len(prices) < period + 1:
        return None
    
    # 简化：假设 OHLC 相同，True Range = 0
    # 这种情况下 ATR 无意义，返回 None
    # 实际使用中应该使用 K 线数据
    
    # 替代方案：计算价格变化的绝对值作为波动率估计
    changes = [abs(prices[i] - prices[i - 1]) for i in range(1, len(prices))]
    
    if len(changes) < period:
        return None
    
    # 使用移动平均
    atr = sum(changes[:period]) / period
    for change in changes[period:]:
        atr = (atr * (period - 1) + change) / period
    
    return atr


# ==================== 异常波动检测 ====================

def check_abnormal_volatility(
    current_price: float,
    window_prices: List[float],
    atr_value: Optional[float],
    config: Optional[Dict[str, Any]] = None
) -> VolatilitySignal:
    """
    检查是否存在异常波动
    
    核心逻辑:
        1. 计算当前价格与滑窗期初价格的落差
        2. 如果 |落差| > k * ATR，触发异常波动信号
        3. 如果 ATR 无效，使用绝对值阈值 fallback_threshold
    
    Args:
        current_price: 当前最新价格
        window_prices: 滑窗价格列表（按时间正序，第一个是期初价格）
        atr_value: ATR 值（动态阈值基准）
        config: 配置字典，包含:
            - k_multiplier: ATR 乘数（灵敏度）
            - fallback_threshold: 降级绝对值阈值
    
    Returns:
        VolatilitySignal: 波动率信号
    
    示例:
        >>> config = {"atr_strategy": {"k_multiplier": 2.5, "fallback_threshold": 10.0}}
        >>> signal = check_abnormal_volatility(
        ...     current_price=2680.0,
        ...     window_prices=[2650.0, 2655.0, 2660.0],
        ...     atr_value=8.0,
        ...     config=config
        ... )
        >>> print(signal.triggered)  # True if |30| > 2.5 * 8 = 20
    """
    # 加载配置
    if config is None:
        config = load_config()
    
    atr_config = config.get("atr_strategy", {})
    k_multiplier = atr_config.get("k_multiplier", 2.5)
    fallback_threshold = atr_config.get("fallback_threshold", 10.0)
    
    # 数据验证
    if not window_prices:
        print("[Indicators] 滑窗价格为空，无法检测异常波动")
        return VolatilitySignal(
            triggered=False,
            current_price=current_price,
            reference_price=0.0,
            price_change=0.0,
            price_change_pct=0.0,
            atr_value=None,
            threshold=fallback_threshold,
            signal_type='none'
        )
    
    # 获取滑窗期初价格（第一个价格）
    reference_price = window_prices[0]
    
    # 计算价格变化
    price_change = current_price - reference_price
    price_change_pct = (price_change / reference_price * 100) if reference_price != 0 else 0.0
    
    # 确定阈值
    use_atr = atr_config.get("enabled", True) and atr_value is not None and atr_value > 0
    
    if use_atr:
        # 使用动态 ATR 阈值
        threshold = k_multiplier * atr_value
        print(f"[Indicators] 使用 ATR 阈值：{threshold:.2f} (k={k_multiplier}, ATR={atr_value:.2f})")
    else:
        # 降级到绝对值阈值
        threshold = fallback_threshold
        print(f"[Indicators] ATR 无效，使用降级阈值：{threshold:.2f}")
    
    # 判断是否触发
    triggered = abs(price_change) > threshold
    
    # 创建信号
    signal = VolatilitySignal(
        triggered=triggered,
        current_price=current_price,
        reference_price=reference_price,
        price_change=price_change,
        price_change_pct=price_change_pct,
        atr_value=atr_value if use_atr else None,
        threshold=threshold,
        signal_type='none'  # 会在 __post_init__ 中更新
    )
    
    if triggered:
        direction = "上涨" if price_change > 0 else "下跌"
        print(f"[Indicators] 异常波动检测：{direction} {abs(price_change_pct):.2f}% "
              f"(阈值={threshold:.2f})")
    
    return signal


def check_volume_surge(
    current_volume: float,
    avg_volume: float,
    surge_ratio: Optional[float] = None,
    config: Optional[Dict[str, Any]] = None
) -> bool:
    """
    检查是否出现放量（成交量激增）
    
    Args:
        current_volume: 当前成交量
        avg_volume: 平均成交量
        surge_ratio: 放量倍数阈值
        config: 配置字典
    
    Returns:
        bool: True 表示放量
    """
    if config is None:
        config = load_config()
    
    if surge_ratio is None:
        surge_ratio = config.get("atr_strategy", {}).get("volume_surge_ratio", 1.5)
    
    if avg_volume <= 0:
        return False
    
    ratio = current_volume / avg_volume
    return ratio >= surge_ratio


# ==================== 多因子分析基础 ====================

def calculate_price_momentum(
    prices: List[float],
    period: int = 5
) -> Optional[float]:
    """
    计算价格动量
    
    动量 = (当前价格 - N 日前价格) / N 日前价格 * 100
    
    Args:
        prices: 价格列表（按时间正序）
        period: 动量周期
    
    Returns:
        float: 动量百分比
    """
    if len(prices) < period + 1:
        return None
    
    current = prices[-1]
    past = prices[-period - 1]
    
    if past == 0:
        return None
    
    momentum = (current - past) / past * 100
    return momentum


def calculate_rsi(
    prices: List[float],
    period: int = 14
) -> Optional[float]:
    """
    计算 RSI（相对强弱指标）
    
    RSI 用于衡量价格的超买超卖状态：
    - RSI > 70: 超买
    - RSI < 30: 超卖
    
    Args:
        prices: 价格列表
        period: RSI 周期
    
    Returns:
        float: RSI 值（0-100）
    """
    if len(prices) < period + 1:
        return None
    
    if PANDAS_AVAILABLE:
        try:
            return _calculate_rsi_pandas(prices, period)
        except Exception as e:
            print(f"[Indicators] pandas RSI 计算失败：{e}")
    
    return _calculate_rsi_pure_python(prices, period)


def _calculate_rsi_pandas(prices: List[float], period: int) -> Optional[float]:
    """使用 pandas 计算 RSI"""
    df = pd.DataFrame({'close': prices})
    
    # 计算价格变化
    delta = df['close'].diff()
    
    # 分离涨跌
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    
    # 计算平均涨跌（指数移动平均）
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    
    # 计算 RS 和 RSI
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    rsi_value = rsi.iloc[-1]
    
    if pd.isna(rsi_value):
        return None
    
    return float(rsi_value)


def _calculate_rsi_pure_python(prices: List[float], period: int) -> Optional[float]:
    """纯 Python 计算 RSI"""
    # 计算价格变化
    changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    
    if len(changes) < period:
        return None
    
    # 分离涨跌
    gains = [change if change > 0 else 0 for change in changes]
    losses = [-change if change < 0 else 0 for change in changes]
    
    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    
    # 平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_ma(
    prices: List[float],
    period: int = 20
) -> Optional[float]:
    """
    计算移动平均线（MA）
    
    Args:
        prices: 价格列表
        period: 周期
    
    Returns:
        float: MA 值
    """
    if len(prices) < period:
        return None
    
    return sum(prices[-period:]) / period


def calculate_bollinger_bands(
    prices: List[float],
    period: int = 20,
    std_multiplier: float = 2.0
) -> Optional[Tuple[float, float, float]]:
    """
    计算布林带
    
    Args:
        prices: 价格列表
        period: 周期
        std_multiplier: 标准差乘数
    
    Returns:
        Tuple: (上轨，中轨，下轨)
    """
    if len(prices) < period:
        return None
    
    import statistics
    
    # 中轨 = MA
    ma = sum(prices[-period:]) / period
    
    # 标准差
    std = statistics.stdev(prices[-period:])
    
    # 上下轨
    upper = ma + std_multiplier * std
    lower = ma - std_multiplier * std
    
    return (upper, ma, lower)


# ==================== 数据清洗工具 ====================

def clean_price_data(
    prices: List[float],
    remove_zeros: bool = True,
    remove_outliers: bool = True,
    outlier_std: float = 5.0
) -> List[float]:
    """
    清洗价格数据
    
    Args:
        prices: 原始价格列表
        remove_zeros: 是否移除零值
        remove_outliers: 是否移除异常值
        outlier_std: 异常值标准差倍数
    
    Returns:
        List[float]: 清洗后的价格
    """
    if not prices:
        return []
    
    cleaned = prices.copy()
    
    # 移除零值和负值
    if remove_zeros:
        cleaned = [p for p in cleaned if p > 0]
    
    # 移除异常值
    if remove_outliers and len(cleaned) > 2:
        import statistics
        
        mean = statistics.mean(cleaned)
        std = statistics.stdev(cleaned)
        
        lower_bound = mean - outlier_std * std
        upper_bound = mean + outlier_std * std
        
        cleaned = [p for p in cleaned if lower_bound <= p <= upper_bound]
    
    return cleaned


def fill_missing_prices(
    prices: List[Optional[float]],
    method: str = 'ffill'
) -> List[float]:
    """
    填充缺失的价格数据
    
    Args:
        prices: 价格列表（可能包含 None）
        method: 填充方法 ('ffill' 前向填充，'bfill' 后向填充，'mean' 均值)
    
    Returns:
        List[float]: 填充后的价格
    """
    if not prices:
        return []
    
    filled = prices.copy()
    n = len(filled)
    
    if method == 'ffill':
        # 前向填充
        last_valid = None
        for i in range(n):
            if filled[i] is not None:
                last_valid = filled[i]
            elif last_valid is not None:
                filled[i] = last_valid
    
    elif method == 'bfill':
        # 后向填充
        last_valid = None
        for i in range(n - 1, -1, -1):
            if filled[i] is not None:
                last_valid = filled[i]
            elif last_valid is not None:
                filled[i] = last_valid
    
    elif method == 'mean':
        # 均值填充
        valid_prices = [p for p in filled if p is not None]
        if valid_prices:
            mean_price = sum(valid_prices) / len(valid_prices)
            filled = [p if p is not None else mean_price for p in filled]
    
    # 处理首尾仍为 None 的情况
    first_valid = next((p for p in filled if p is not None), None)
    if first_valid is not None:
        filled = [p if p is not None else first_valid for p in filled]
    
    return filled  # type: ignore


# ==================== 使用示例 ====================

if __name__ == "__main__":
    print("=== Indicators 使用示例 ===\n")
    
    # 模拟价格数据
    import random
    random.seed(42)
    
    base_price = 2650.0
    prices = [base_price]
    for _ in range(100):
        change = random.gauss(0, 5)
        prices.append(prices[-1] + change)
    
    print(f"生成 {len(prices)} 条价格数据，范围：{min(prices):.2f} - {max(prices):.2f}\n")
    
    # 测试 ATR 计算
    print("--- ATR 计算 ---")
    # 简化：使用价格变化作为 ATR 估计
    atr = calculate_atr_from_ticks(prices, period=14)
    print(f"ATR(14): {atr:.2f}" if atr else "ATR: None")
    
    # 测试异常波动检测
    print("\n--- 异常波动检测 ---")
    config = load_config()
    print(f"配置：k_multiplier={config['atr_strategy']['k_multiplier']}, "
          f"fallback_threshold={config['atr_strategy']['fallback_threshold']}")
    
    # 模拟当前价格大幅上涨
    current_price = prices[-1] + 25  # 上涨 25 美元
    window = prices[-20:]  # 最近 20 条
    
    signal = check_abnormal_volatility(
        current_price=current_price,
        window_prices=window,
        atr_value=atr,
        config=config
    )
    
    print(f"\n检测结果：{signal}")
    print(f"  - 当前价格：{signal.current_price:.2f}")
    f"  - 参考价格：{signal.reference_price:.2f}"
    print(f"  - 价格变化：{signal.price_change:.2f} ({signal.price_change_pct:.2f}%)")
    print(f"  - 触发阈值：{signal.threshold:.2f}")
    print(f"  - 信号类型：{signal.signal_type}")
    
    # 测试 RSI
    print("\n--- RSI 计算 ---")
    rsi = calculate_rsi(prices, period=14)
    print(f"RSI(14): {rsi:.2f}" if rsi else "RSI: None")
    
    if rsi:
        if rsi > 70:
            print("状态：超买")
        elif rsi < 30:
            print("状态：超卖")
        else:
            print("状态：中性")
    
    # 测试移动平均
    print("\n--- 移动平均 ---")
    ma20 = calculate_ma(prices, period=20)
    ma50 = calculate_ma(prices, period=50)
    print(f"MA(20): {ma20:.2f}" if ma20 else "MA(20): None")
    print(f"MA(50): {ma50:.2f}" if ma50 else "MA(50): None")
    
    # 测试布林带
    print("\n--- 布林带 ---")
    bb = calculate_bollinger_bands(prices, period=20)
    if bb:
        upper, mid, lower = bb
        print(f"上轨：{upper:.2f}")
        print(f"中轨：{mid:.2f}")
        print(f"下轨：{lower:.2f}")
        print(f"当前价格位置：{'上轨上方' if current_price > upper else '下轨下方' if current_price < lower else '布林带内'}")
