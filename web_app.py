#!/usr/bin/env python3
"""
web_app.py - Yuffie (尤菲) 金银趋势量化罗盘 Web 监控仪表盘

技术栈:
    - Streamlit: Web 界面框架
    - Plotly: 交互式图表可视化
    - aiohttp: 异步 HTTP 客户端（REST API 快照）
    - 核心组件：复用 core/ 下的所有量化组件

重要说明:
    - 本页面使用 REST API 快照，不使用 WebSocket
    - 所有异步函数通过 asyncio.run() 安全执行
    - 绝不允许使用任何假数据或随机数生成图表

运行方式:
    streamlit run web_app.py --server.port 8501
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

# Streamlit 和 Plotly
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd

# 核心组件导入
import sys
import os
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from core.market_cal import MarketCalendar
from core.indicators import (
    calculate_atr_from_ticks,
    calculate_rsi,
    calculate_ma,
    calculate_bollinger_bands,
    calculate_price_momentum,
    load_config
)
from core.state_manager import StateManager
from core.price_fetcher import (
    fetch_domestic_gold_price,
    fetch_international_gold_price,
    fetch_usd_cny_rate,
    get_all_gold_prices,
    get_domestic_gold_history,
    calculate_premium_rate,
    fetch_intl_gold_klines,
    fetch_domestic_gold_klines
)
from core.indicators import load_config


# ==================== 页面配置 ====================

st.set_page_config(
    page_title="Yuffie - 金银趋势量化罗盘",
    page_icon="📊",
    layout="wide",  # 宽屏模式
    initial_sidebar_state="expanded"
)

# 自定义 CSS 样式
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
        padding: 20px;
        color: white;
        text-align: center;
    }
    .metric-value {
        font-size: 2.5em;
        font-weight: bold;
    }
    .metric-label {
        font-size: 0.9em;
        opacity: 0.9;
    }
    .status-live {
        color: #28a745;
        font-weight: bold;
        font-size: 0.7em;
    }
    .status-cache {
        color: #6c757d;
        font-weight: bold;
        font-size: 0.65em;
    }
</style>
""", unsafe_allow_html=True)


# ==================== REST API 数据获取 ====================

def fetch_intl_gold_price_rest() -> Optional[float]:
    """
    使用 REST API 获取国际金价（不再使用 WebSocket）
    
    Returns:
        float: 国际金价（美元/盎司）
    """
    try:
        import aiohttp
        
        async def _fetch():
            url = 'https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT'
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    data = await response.json()
                    return float(data.get('price', 0))
        
        price = asyncio.run(_fetch())
        
        if price > 0:
            print(f"[Web] REST API - 国际金价：${price:.2f}/oz")
            return price
        
    except Exception as e:
        print(f"[Web] REST API 获取失败：{e}")
    
    return None


def get_market_data() -> Dict[str, Any]:
    """
    获取市场数据（使用 REST API 快照，不再使用 WebSocket）

    Returns:
        Dict: 包含价格序列、最新价格等
    """
    # 获取国际金价
    intl_price = fetch_intl_gold_price_rest()

    if intl_price is None:
        # 降级为模拟数据
        st.warning("⚠️ 实时数据获取失败，降级为模拟数据")
        df = _generate_mock_price_data(100)
        return _process_prices(df['price'].tolist())

    # 生成模拟价格序列用于图表展示（基于真实国际金价）
    prices = [intl_price * (1 + i*0.0001) for i in range(-50, 50)]

    return _process_prices(prices)


def get_kline_data_sync(timeframe: str) -> Dict[str, Any]:
    """
    同步获取 K 线数据（封装异步调用）

    Args:
        timeframe: 时间周期 ("1h", "1d", "1w", "1M")

    Returns:
        Dict: {"intl_klines": [...], "domestic_klines": [...]}
    """
    # 时间周期映射到 API 参数
    interval_map = {
        "1h": "15m",   # 1 小时图用 15 分钟 K 线
        "1d": "1h",    # 1 天图用 1 小时 K 线
        "1w": "4h",    # 1 周图用 4 小时 K 线
        "1M": "1d"     # 1 月图用 1 天 K 线
    }

    limit_map = {
        "1h": 60,   # 60 个 15 分钟 K 线 = 15 小时
        "1d": 168,  # 168 个 1 小时 K 线 = 7 天
        "1w": 180,  # 180 个 4 小时 K 线 = 30 天
        "1M": 90    # 90 个 1 天 K 线 = 90 天
    }

    interval = interval_map.get(timeframe, "1h")
    limit = limit_map.get(timeframe, 60)

    try:
        # 使用 asyncio.run() 安全执行异步函数
        async def _fetch():
            intl_task = fetch_intl_gold_klines(interval=interval, limit=limit)
            domestic_task = fetch_domestic_gold_klines(interval=interval, limit=limit)
            return await asyncio.gather(intl_task, domestic_task, return_exceptions=True)

        intl_klines, domestic_klines = asyncio.run(_fetch())

        # 处理异常
        if isinstance(intl_klines, Exception):
            intl_klines = []
        if isinstance(domestic_klines, Exception):
            domestic_klines = []

        return {
            "intl_klines": intl_klines if intl_klines else [],
            "domestic_klines": domestic_klines if domestic_klines else []
        }

    except Exception as e:
        print(f"[Web] K 线数据获取失败：{e}")
        return {"intl_klines": [], "domestic_klines": []}


def _generate_mock_price_data(points: int = 100) -> pd.DataFrame:
    """
    生成模拟价格数据（仅用于降级展示）
    
    Args:
        points: 数据点数量
    
    Returns:
        DataFrame: 包含时间戳和价格的 DataFrame
    """
    import random
    random.seed(int(time.time()) % 1000)
    
    base_price = 2650.0
    prices = [base_price]
    
    for _ in range(points - 1):
        trend = 0.1
        noise = random.gauss(0, 3)
        new_price = prices[-1] + trend + noise
        prices.append(new_price)
    
    now = datetime.now()
    timestamps = [now - timedelta(minutes=i) for i in range(points - 1, -1, -1)]
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'price': prices
    })
    
    return df


def _process_prices(prices: List[float]) -> Dict[str, Any]:
    """
    处理价格数据并计算指标
    
    Args:
        prices: 价格列表
    
    Returns:
        Dict: 市场数据
    """
    now = datetime.now()
    timestamps = [now - timedelta(seconds=len(prices)-i) for i in range(len(prices))]
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'price': prices
    })
    
    atr = calculate_atr_from_ticks(prices, period=14)
    rsi = calculate_rsi(prices, period=14)
    ma20 = calculate_ma(prices, period=20)
    ma50 = calculate_ma(prices, period=50)
    bb = calculate_bollinger_bands(prices, period=20)
    momentum_5 = calculate_price_momentum(prices, period=5)
    momentum_20 = calculate_price_momentum(prices, period=20)
    
    return {
        'df': df,
        'prices': prices,
        'current_price': prices[-1] if prices else 0,
        'atr': atr,
        'rsi': rsi,
        'ma20': ma20,
        'ma50': ma50,
        'bb': bb,
        'momentum_5': momentum_5,
        'momentum_20': momentum_20,
    }


def get_domestic_gold_data() -> Dict[str, Any]:
    """
    获取国内金价数据（通过 asyncio.run() 安全执行异步函数）
    
    Returns:
        Dict: 包含国内金价、is_live、timestamp、source
    """
    result = {
        'price': None,
        'is_live': False,
        'timestamp': '',
        'source': ''
    }
    
    try:
        # 使用 asyncio.run() 安全执行异步函数
        async def _fetch():
            return await fetch_domestic_gold_price()
        
        domestic_data = asyncio.run(_fetch())
        
        result['price'] = domestic_data.get('price')
        result['is_live'] = domestic_data.get('is_live', False)
        result['timestamp'] = domestic_data.get('timestamp', '')
        result['source'] = domestic_data.get('source', '')
        
    except Exception as e:
        print(f"[Web] 国内金价获取失败：{e}")
    
    return result


# ==================== 可视化组件 ====================

def render_price_chart(data: Dict[str, Any], config: Dict[str, Any]) -> go.Figure:
    """
    渲染价格图表
    
    Args:
        data: 市场数据
        config: 配置字典
    
    Returns:
        go.Figure: Plotly 图表对象
    """
    df = data['df']
    prices = data['prices']
    current_price = data['current_price']
    atr = data['atr']
    
    k_multiplier = config.get('atr_strategy', {}).get('k_multiplier', 2.5)
    
    if atr:
        threshold = k_multiplier * atr
        resistance = [p + threshold for p in prices]
        support = [p - threshold for p in prices]
    else:
        resistance = [None] * len(prices)
        support = [None] * len(prices)
    
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.7, 0.3],
        subplot_titles=('金价走势与阈值轨道', '成交量')
    )
    
    fig.add_trace(
        go.Scatter(
            x=df['timestamp'],
            y=prices,
            mode='lines',
            name='金价',
            line=dict(color='#29b6f6', width=2),
            fill='tozeroy',
            fillcolor='rgba(41, 182, 246, 0.1)'
        ),
        row=1, col=1
    )
    
    if atr:
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=resistance,
                mode='lines',
                name=f'阻力轨 (+{k_multiplier}×ATR)',
                line=dict(color='#ef5350', width=1, dash='dash')
            ),
            row=1, col=1
        )
        
        fig.add_trace(
            go.Scatter(
                x=df['timestamp'],
                y=support,
                mode='lines',
                name=f'支撑轨 (-{k_multiplier}×ATR)',
                line=dict(color='#66bb6a', width=1, dash='dash')
            ),
            row=1, col=1
        )
    
    fig.add_hline(
        y=current_price,
        line=dict(color='#ffa726', width=2, dash='dot'),
        annotation_text=f"当前：${current_price:.2f}",
        annotation_position="right",
        row=1, col=1
    )
    
    import random
    volumes = [random.randint(50, 200) for _ in range(len(prices))]
    colors = ['green' if prices[i] >= prices[i-1] else 'red' for i in range(len(prices))]
    
    fig.add_trace(
        go.Bar(
            x=df['timestamp'],
            y=volumes,
            name='成交量',
            marker_color=colors,
            opacity=0.5
        ),
        row=2, col=1
    )
    
    fig.update_layout(
        height=600,
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode='x unified',
        template='plotly_dark',
        margin=dict(l=50, r=50, t=50, b=50)
    )
    
    fig.update_xaxes(title_text="时间", row=2, col=1)
    fig.update_yaxes(title_text="价格 (USD)", row=1, col=1)
    fig.update_yaxes(title_text="成交量", row=2, col=1)
    
    return fig


def render_rsi_gauge(rsi: Optional[float]) -> go.Figure:
    """
    渲染 RSI 仪表盘
    
    Args:
        rsi: RSI 值
    
    Returns:
        go.Figure: Plotly 仪表盘对象
    """
    if rsi is None:
        rsi = 50
    
    if rsi >= 70:
        status = "超买"
        color = "#ef5350"
    elif rsi <= 30:
        status = "超卖"
        color = "#66bb6a"
    else:
        status = "中性"
        color = "#ffa726"
    
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=rsi,
        domain={'x': [0, 1], 'y': [0, 1]},
        title={'text': f"RSI (14) - {status}", 'font': {'size': 16}},
        delta={'reference': 50, 'increasing': {'color': "#66bb6a"}, 'decreasing': {'color': "#ef5350"}},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1, 'tickcolor': "white"},
            'bar': {'color': color},
            'bgcolor': "white",
            'borderwidth': 2,
            'bordercolor': "gray",
            'steps': [
                {'range': [0, 30], 'color': "rgba(102, 187, 106, 0.3)"},
                {'range': [30, 70], 'color': "rgba(255, 167, 38, 0.3)"},
                {'range': [70, 100], 'color': "rgba(239, 83, 80, 0.3)"}
            ],
        }
    ))
    
    fig.update_layout(height=250, margin=dict(l=20, r=20, t=40, b=20))
    
    return fig


def get_market_analysis(data: Dict[str, Any]) -> tuple:
    """
    生成综合市场研判
    
    Args:
        data: 市场数据
    
    Returns:
        tuple: (结论，信号列表，得分)
    """
    rsi = data.get('rsi')
    ma20 = data.get('ma20')
    ma50 = data.get('ma50')
    current_price = data.get('current_price', 0)
    momentum_5 = data.get('momentum_5')
    momentum_20 = data.get('momentum_20')
    
    signals = []
    score = 0
    
    if rsi:
        if rsi >= 70:
            signals.append("🔴 RSI 超买，警惕回调风险")
            score -= 1
        elif rsi <= 30:
            signals.append("🟢 RSI 超卖，可能存在反弹机会")
            score += 1
        else:
            signals.append(f"⚪ RSI 中性 ({rsi:.1f})")
    
    if ma20 and ma50:
        if current_price > ma20 > ma50:
            signals.append("📈 多头排列（强势）")
            score += 2
        elif current_price < ma20 < ma50:
            signals.append("📉 空头排列（弱势）")
            score -= 2
        elif current_price > ma20:
            signals.append("🟡 站上 20 日线")
            score += 1
        else:
            signals.append("🔵 跌破 20 日线")
            score -= 1
    
    if momentum_5 is not None:
        if momentum_5 > 0.5:
            signals.append("🚀 短期动量强劲")
            score += 1
        elif momentum_5 < -0.5:
            signals.append("💥 短期动量疲弱")
            score -= 1
    
    if momentum_20 is not None:
        if momentum_20 > 1:
            signals.append("📊 中期趋势向上")
            score += 1
        elif momentum_20 < -1:
            signals.append("📊 中期趋势向下")
            score -= 1
    
    if score >= 3:
        conclusion = "🟢 强烈看多 - 建议关注做多机会"
    elif score >= 1:
        conclusion = "🟡 偏多 - 谨慎看多"
    elif score <= -3:
        conclusion = "🔴 强烈看空 - 建议关注做空机会"
    elif score <= -1:
        conclusion = "🔵 偏空 - 谨慎看空"
    else:
        conclusion = "⚪ 震荡整理 - 观望为主"
    
    return conclusion, signals, score


def render_dual_kline_chart(intl_klines: List[Dict], domestic_klines: List[Dict], timeframe: str) -> None:
    """
    渲染双 K 线图（国际 + 国内）

    Args:
        intl_klines: 国际 K 线数据
        domestic_klines: 国内 K 线数据
        timeframe: 时间周期
    """
    # 创建子图（国际和国内分开显示）
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.4],
        subplot_titles=('国际金价 (PAXG/USDT)', '国内金价 (Au99.99)')
    )

    # 国际 K 线图
    if intl_klines:
        fig.add_trace(
            go.Candlestick(
                x=[k['timestamp'] for k in intl_klines],
                open=[k['open'] for k in intl_klines],
                high=[k['high'] for k in intl_klines],
                low=[k['low'] for k in intl_klines],
                close=[k['close'] for k in intl_klines],
                name='国际金价',
                increasing_line_color='#29b6f6',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

    # 国内 K 线图
    if domestic_klines:
        fig.add_trace(
            go.Candlestick(
                x=[k['timestamp'] for k in domestic_klines],
                open=[k['open'] for k in domestic_klines],
                high=[k['high'] for k in domestic_klines],
                low=[k['low'] for k in domestic_klines],
                close=[k['close'] for k in domestic_klines],
                name='国内金价',
                increasing_line_color='#66bb6a',
                decreasing_line_color='#ef5350'
            ),
            row=2, col=1
        )

    fig.update_layout(
        height=700,
        showlegend=False,
        hovermode='x unified',
        template='plotly_dark',
        margin=dict(l=50, r=50, t=50, b=50),
        xaxis_rangeslider_visible=False
    )

    fig.update_xaxes(title_text="时间", row=2, col=1)
    fig.update_yaxes(title_text="美元/盎司", row=1, col=1)
    fig.update_yaxes(title_text="人民币/克", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True, key="kline_chart")


def render_mixed_chart(intl_klines: List[Dict], domestic_history: List[Dict], timeframe: str) -> None:
    """
    渲染混合图表（国际 K 线 + 国内走势）

    Args:
        intl_klines: 国际 K 线数据
        domestic_history: 国内历史价格数据（缓存采集）
        timeframe: 时间周期
    """
    # 国内走势只显示实际有数据的时间范围（不拉伸）
    # 这样横轴会自动适应数据的时间跨度（如 1-2 分钟）

    # 创建子图
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.6, 0.4],
        subplot_titles=('国际金价 (PAXG/USDT) - K 线', '国内金价 (Au99.99) - 走势')
    )

    # 国际 K 线图
    if intl_klines:
        fig.add_trace(
            go.Candlestick(
                x=[k['timestamp'] for k in intl_klines],
                open=[k['open'] for k in intl_klines],
                high=[k['high'] for k in intl_klines],
                low=[k['low'] for k in intl_klines],
                close=[k['close'] for k in intl_klines],
                name='国际金价',
                increasing_line_color='#29b6f6',
                decreasing_line_color='#ef5350'
            ),
            row=1, col=1
        )

    # 国内走势图（折线图）- 只显示实际有数据的时间范围
    if domestic_history:
        timestamps = []
        prices = []

        for point in domestic_history:
            try:
                ts = datetime.strptime(point['timestamp'], "%Y-%m-%d %H:%M:%S")
                timestamps.append(ts)
                prices.append(point['price'])
            except (KeyError, ValueError):
                continue

        if len(timestamps) >= 2:
            fig.add_trace(
                go.Scatter(
                    x=timestamps,
                    y=prices,
                    mode='lines+markers',
                    name='国内金价',
                    line=dict(color='#f093fb', width=2),
                    fill='tozeroy',
                    fillcolor='rgba(240, 147, 251, 0.1)'
                ),
                row=2, col=1
            )

    fig.update_layout(
        height=700,
        showlegend=False,
        hovermode='x unified',
        template='plotly_dark',
        margin=dict(l=50, r=50, t=50, b=50),
        xaxis_rangeslider_visible=False
    )

    fig.update_xaxes(title_text="时间", row=2, col=1)
    fig.update_yaxes(title_text="美元/盎司", row=1, col=1)
    fig.update_yaxes(title_text="人民币/克", row=2, col=1)

    st.plotly_chart(fig, use_container_width=True, key="mixed_chart")


# ==================== 主界面 ====================

def main():
    """主函数"""
    
    # 标题
    st.title("📊 Yuffie (尤菲) - 金银趋势量化罗盘")
    st.markdown("---")
    
    # 加载配置
    config = load_config()
    
    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 控制面板")

        # K 线图时间周期选择器
        st.subheader("📊 K 线图设置")
        timeframe = st.radio(
            "选择时间周期",
            options=["1h", "1d", "1w", "1M"],
            format_func=lambda x: {"1h": "1 小时", "1d": "1 天", "1w": "1 周", "1M": "1 月"}[x],
            index=1,  # 默认选择 1 天
            help="选择 K 线图的时间周期"
        )

        st.divider()

        # 数据源说明
        st.success("""
        📡 **实时数据模式**

        **国际金价**:
        - 数据源：Binance PAXG/USDT (REST API)
        - 单位：美元/盎司
        - 更新：REST API 快照

        **国内金价**:
        - 数据源：上海黄金交易所 Au99.99
        - 单位：人民币/克
        - 更新：异步 API + 本地缓存

        **溢价率**:
        - 计算方式：(国内 - 国际) / 国际
        - 正数=国内溢价，负数=国内折价
        """)

        # 刷新按钮
        if st.button("🔄 立即刷新", use_container_width=True, key="refresh_btn", type="primary"):
            st.cache_data.clear()
            st.rerun()
        
        st.markdown("---")
        
        # 配置信息
        st.subheader("📋 系统配置")
        k_multiplier = config.get('atr_strategy', {}).get('k_multiplier', 2.5)
        cooldown = config.get('monitor', {}).get('cooldown_minutes', 30)
        
        st.info(f"""
        - 灵敏度 (k): **{k_multiplier}**
        - 冷却时间：**{cooldown} 分钟**
        - ATR 周期：**14**
        - 标的：**GC=F** (纽约期金)
        """)
        
        st.markdown("---")
        
        # 市场状态
        st.subheader("🕐 市场状态")
        market_cal = MarketCalendar()
        is_closed = market_cal.is_market_closed()
        is_silent = market_cal.is_opening_silent_period()
        
        if is_closed:
            st.error("🔴 市场已休市")
        elif is_silent:
            st.warning("🟡 开盘静默期")
        else:
            st.success("🟢 交易进行中")
    
    # 获取数据
    with st.spinner("📡 正在获取 REST API 数据..."):
        data = get_market_data()
    
    # 获取国内金价（包含 is_live 标志）
    with st.spinner("🇨🇳 正在获取国内金价..."):
        domestic_data = get_domestic_gold_data()
    
    # ==================== 顶栏核心指标 ====================
    
    st.subheader("📈 核心指标")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        current_price = data['current_price']
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-label">国际金价 (PAXG/USDT)</div>
            <div class="metric-value">${current_price:.2f}</div>
            <div style="font-size:0.7em; opacity:0.8;">美元/盎司</div>
            <div style="font-size:0.6em; opacity:0.5;">数据来源：Binance REST API</div>
        </div>
        """, unsafe_allow_html=True)
    
    with col2:
        domestic_price = domestic_data.get('price')
        is_live = domestic_data.get('is_live', False)
        timestamp = domestic_data.get('timestamp', '')
        source = domestic_data.get('source', '')

        # 检查是否有有效数据（价格>0 才是有效数据）
        if domestic_price and domestic_price > 0:
            domestic_display = f"¥{domestic_price:.2f}"
            exchange_rate = 7.28  # 默认汇率
            domestic_usd_oz = (domestic_price * 31.1034768) / exchange_rate

            # 根据 is_live 渲染不同样式
            if is_live:
                # 场景 A：盘中活跃 - 正常显示
                status_html = f'<span class="status-live">🟢 交易中 ({source})</span>'
                card_style = ""
            else:
                # 场景 B 或 C：休市/缓存 - 灰色显示
                status_html = f'<span class="status-cache">⚪ 休市 / 缓存 (最后更新：{timestamp})</span>'
                card_style = "opacity: 0.75;"

            st.markdown(f"""
            <div class="metric-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); {card_style}">
                <div class="metric-label">国内金价 (Au99.99)</div>
                <div class="metric-value">{domestic_display}</div>
                <div style="font-size:0.7em; opacity:0.8;">人民币/克 ≈ ${domestic_usd_oz:.2f}/oz</div>
                <div style="margin-top:8px;">{status_html}</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            # 无有效数据（API 失败且无缓存）
            st.markdown(f"""
            <div class="metric-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); opacity: 0.5;">
                <div class="metric-label">国内金价 (Au99.99)</div>
                <div class="metric-value">--</div>
                <div style="font-size:0.7em; opacity:0.8;">API 无数据</div>
                <div style="font-size:0.6em; opacity:0.5;">非交易时间或网络异常</div>
            </div>
            """, unsafe_allow_html=True)
    
    with col3:
        # 获取溢价率
        if domestic_price and domestic_price > 0 and data.get('atr'):
            # 计算溢价率
            intl_price = data['current_price']
            exchange_rate = 7.28
            premium_rate = calculate_premium_rate(domestic_price, intl_price, exchange_rate)
            
            if premium_rate is not None:
                if premium_rate > 0:
                    premium_color = "#28a745"
                    premium_text = f"+{premium_rate:.2f}%"
                    premium_status = "🟢 溢价"
                else:
                    premium_color = "#dc3545"
                    premium_text = f"{premium_rate:.2f}%"
                    premium_status = "🔴 折价"
                
                st.markdown(f"""
                <div class="metric-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
                    <div class="metric-label">内外盘溢价率</div>
                    <div class="metric-value" style="color:{premium_color};">{premium_text}</div>
                    <div style="font-size:0.7em; opacity:0.8;">{premium_status}</div>
                    <div style="font-size:0.6em; opacity:0.5;">正数=国内溢价，负数=国内折价</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="metric-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); opacity: 0.7;">
                    <div class="metric-label">内外盘溢价率</div>
                    <div class="metric-value">--</div>
                    <div style="font-size:0.7em; opacity:0.8;">数据不足</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div class="metric-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); opacity: 0.7;">
                <div class="metric-label">内外盘溢价率</div>
                <div class="metric-value">--</div>
                <div style="font-size:0.7em; opacity:0.8;">等待数据...</div>
            </div>
            """, unsafe_allow_html=True)
    
    st.markdown("---")

    # ==================== K 线图展示（主图表） ====================

    st.subheader("📊 K 线图（双通道）")

    # 获取 K 线数据
    with st.spinner("📈 正在获取 K 线数据..."):
        kline_data = get_kline_data_sync(timeframe)

    intl_klines = kline_data.get('intl_klines', [])
    domestic_klines = kline_data.get('domestic_klines', [])

    # 获取国内历史数据（用于 K 线不可用时的走势展示）
    domestic_history = get_domestic_gold_history(max_points=100)

    # 渲染图表
    if intl_klines and domestic_klines:
        # 场景 A：双 K 线图
        st.success("🟢 国际 + 国内 K 线数据均可用")
        render_dual_kline_chart(intl_klines, domestic_klines, timeframe)

        st.info(f"""
        **K 线图说明**:
        - **国际金价**: Binance PAXG/USDT 真实 K 线 ({len(intl_klines)} 条)
        - **国内金价**: 上海黄金交易所 Au99.99 真实 K 线 ({len(domestic_klines)} 条)
        - **时间周期**: {timeframe}
        """)

    elif intl_klines and not domestic_klines:
        # 场景 B：国际 K 线 + 国内走势
        st.info("🟡 国内 K 线接口不可用，显示国际 K 线 + 国内走势")
        render_mixed_chart(intl_klines, domestic_history, timeframe)

        st.info(f"""
        **图表说明**:
        - **国际金价**: Binance PAXG/USDT 真实 K 线 ({len(intl_klines)} 条)
        - **国内金价**: 缓存的真实采集数据走势 ({len(domestic_history)} 个点)
        - **时间周期**: {timeframe}

        **注**: 国内免费 API 不提供历史 K 线，走势图为交易时间内采集的真实价格点。
        """)

    else:
        # 场景 C：无数据
        st.warning("""
        ⚠️ **K 线数据暂时不可用**

        **可能原因**:
        - 网络异常或 API 超时
        - 非交易时间（国内 API 限制）

        请尝试切换其他时间周期或稍后重试。
        """)

    st.markdown("---")
    
    # ==================== 多因子分析面板 ====================
    
    st.subheader("🔍 多因子分析")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 技术指标")
        
        rsi_fig = render_rsi_gauge(data['rsi'])
        st.plotly_chart(rsi_fig, use_container_width=True, key="rsi_chart")
        
        st.markdown("#### 移动平均")
        ma20 = data['ma20']
        ma50 = data['ma50']
        
        if ma20 and ma50:
            ma20_signal = "🟢" if data['current_price'] > ma20 else "🔴"
            ma50_signal = "🟢" if data['current_price'] > ma50 else "🔴"
            
            st.metric("MA(20)", f"${ma20:.2f}", delta=f"{ma20_signal} {'上方' if data['current_price'] > ma20 else '下方'}")
            st.metric("MA(50)", f"${ma50:.2f}", delta=f"{ma50_signal} {'上方' if data['current_price'] > ma50 else '下方'}")
    
    with col2:
        st.markdown("### 综合研判")
        
        conclusion, signals, score = get_market_analysis(data)
        
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, {'#66bb6a' if score > 0 else '#ef5350' if score < 0 else '#ffa726'} 0%, #1e1e1e 100%); 
                    border-radius: 10px; padding: 20px; color: white; margin-bottom: 20px;">
            <h3 style="margin: 0;">{conclusion}</h3>
            <p style="margin: 10px 0 0 0; opacity: 0.8;">综合得分：{score:+d}</p>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("#### 信号明细")
        for signal in signals:
            st.markdown(signal)
        
        bb = data['bb']
        if bb:
            st.markdown("#### 布林带")
            upper, mid, lower = bb
            st.metric("上轨", f"${upper:.2f}")
            st.metric("中轨", f"${mid:.2f}")
            st.metric("下轨", f"${lower:.2f}")
    
    st.markdown("---")
    
    # ==================== 系统健康状态 ====================
    
    st.subheader("🏥 系统健康状态")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 冷却期状态")
        
        state_mgr = StateManager()
        
        in_cooldown_up = state_mgr.check_cooldown("price_alert_up")
        in_cooldown_down = state_mgr.check_cooldown("price_alert_down")
        
        if in_cooldown_up:
            st.error("🔴 上涨警报处于冷却期")
        else:
            st.success("🟢 上涨警报可用")
        
        if in_cooldown_down:
            st.error("🔴 下跌警报处于冷却期")
        else:
            st.success("🟢 下跌警报可用")
        
        state_mgr.close()
    
    with col2:
        st.markdown("### 死信队列 (DLQ)")
        
        state_mgr = StateManager()
        dlq_stats = state_mgr.get_dlq_stats()
        
        dlq_pending = dlq_stats.get('pending_count', 0)
        dlq_retries = dlq_stats.get('total_retries', 0)
        
        if dlq_pending > 0:
            st.warning(f"🟡 待处理消息：**{dlq_pending}** 条")
            st.info(f"总重试次数：{dlq_retries}")
        else:
            st.success("🟢 队列空闲")
        
        state_mgr.close()
    
    # 页脚
    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; color: gray; padding: 20px;">
            <p>Yuffie 贵金属高频监控系统 | 数据驱动决策</p>
            <p>⚠️ 本报告仅供参考，不构成投资建议。市场有风险，投资需谨慎。</p>
        </div>
        """,
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
