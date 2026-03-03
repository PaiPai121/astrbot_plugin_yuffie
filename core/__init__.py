"""
core - Yuffie 贵金属监控系统基础设施层

包含:
    - state_manager: 状态持久化与死信队列
    - market_cal: 交易日历管理（CME）
    - data_stream: 高频数据流引擎（WebSocket + 滑窗）
    - indicators: 量化计算引擎（ATR + 波动率检测）
    - price_fetcher: 金价数据获取（国内/国际/汇率）- 异步版本
"""

from .state_manager import StateManager
from .market_cal import MarketCalendar
from .data_stream import (
    HighFrequencyDataStream,
    MockDataStream,
    TickData,
    StreamEvent,
    CircuitBreakerException,
    DataStreamError,
    create_data_stream
)
from .indicators import (
    calculate_atr,
    calculate_atr_from_ticks,
    check_abnormal_volatility,
    check_volume_surge,
    calculate_rsi,
    calculate_ma,
    calculate_bollinger_bands,
    calculate_price_momentum,
    clean_price_data,
    fill_missing_prices,
    VolatilitySignal,
    OHLCV,
    load_config
)
from .price_fetcher import (
    fetch_domestic_gold_price,
    fetch_international_gold_price,
    fetch_usd_cny_rate,
    get_all_gold_prices,
    get_domestic_gold_history,
    calculate_premium_rate,
    fetch_intl_gold_klines,
    fetch_domestic_gold_klines
)

__all__ = [
    # Sprint 1
    "StateManager",
    "MarketCalendar",

    # Sprint 2
    "HighFrequencyDataStream",
    "MockDataStream",
    "TickData",
    "StreamEvent",
    "CircuitBreakerException",
    "DataStreamError",
    "create_data_stream",

    # Indicators
    "calculate_atr",
    "calculate_atr_from_ticks",
    "check_abnormal_volatility",
    "check_volume_surge",
    "calculate_rsi",
    "calculate_ma",
    "calculate_bollinger_bands",
    "calculate_price_momentum",
    "clean_price_data",
    "fill_missing_prices",
    "VolatilitySignal",
    "OHLCV",
    "load_config",

    # Price Fetcher (异步版本)
    "fetch_domestic_gold_price",
    "fetch_international_gold_price",
    "fetch_usd_cny_rate",
    "get_all_gold_prices",
    "get_domestic_gold_history",
    "calculate_premium_rate",
    "fetch_intl_gold_klines",
    "fetch_domestic_gold_klines"
]
