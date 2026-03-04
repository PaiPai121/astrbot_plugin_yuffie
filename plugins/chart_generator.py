"""
chart_generator.py - 图表生成

实现:
    - 使用 plotly 生成价格走势图
    - 支持保存为图片或直接生成 HTML
"""

import os
import io
import base64
from typing import Optional, List, Tuple
from datetime import datetime, timedelta

try:
    import plotly.graph_objects as go
    import plotly.io as pio
    PLOTLY_AVAILABLE = True
except ImportError:
    PLOTLY_AVAILABLE = False


def generate_price_chart(
    prices: List[float],
    timestamps: Optional[List[datetime]] = None,
    title: str = "金价走势",
    width: int = 800,
    height: int = 400
) -> Optional[bytes]:
    """
    生成价格走势图（PNG 图片）
    
    Args:
        prices: 价格列表
        timestamps: 时间戳列表（可选）
        title: 图表标题
        width: 宽度
        height: 高度
    
    Returns:
        bytes: PNG 图片数据
    """
    if not PLOTLY_AVAILABLE:
        return None
    
    try:
        # 创建时间轴
        if timestamps is None:
            now = datetime.now()
            timestamps = [now - timedelta(minutes=i) for i in range(len(prices)-1, -1, -1)]
        
        # 创建图表
        fig = go.Figure()
        
        # 添加价格线
        fig.add_trace(go.Scatter(
            x=timestamps,
            y=prices,
            mode='lines',
            name='价格',
            line=dict(color='#29b6f6', width=2),
            fill='tozeroy',
            fillcolor='rgba(41, 182, 246, 0.1)'
        ))
        
        # 添加移动平均线（如果数据足够）
        if len(prices) >= 20:
            ma20 = _calculate_ma(prices, 20)
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=ma20,
                mode='lines',
                name='MA20',
                line=dict(color='#ffa726', width=1, dash='dash')
            ))
        
        # 更新布局
        fig.update_layout(
            title=title,
            xaxis_title="时间",
            yaxis_title="价格 (USD)",
            width=width,
            height=height,
            template='plotly_dark',
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=50, r=50, t=50, b=50)
        )
        
        # 更新坐标轴
        fig.update_xaxes(
            tickformat="%H:%M",
            tickangle=45
        )
        
        fig.update_yaxes(
            tickprefix="$",
            tickformat=".2f"
        )
        
        # 转换为 PNG
        img_bytes = pio.to_image(fig, format="png", width=width, height=height)
        
        return img_bytes
        
    except Exception as e:
        print(f"[ChartGenerator] 生成图表失败：{e}")
        return None


def generate_candlestick_chart(
    opens: List[float],
    highs: List[float],
    lows: List[float],
    closes: List[float],
    timestamps: Optional[List[datetime]] = None,
    title: str = "K 线图",
    width: int = 800,
    height: int = 500
) -> Optional[bytes]:
    """
    生成 K 线图
    
    Args:
        opens: 开盘价列表
        highs: 最高价列表
        lows: 最低价列表
        closes: 收盘价列表
        timestamps: 时间戳列表
        title: 图表标题
        width: 宽度
        height: 高度
    
    Returns:
        bytes: PNG 图片数据
    """
    if not PLOTLY_AVAILABLE:
        return None
    
    try:
        # 创建时间轴
        if timestamps is None:
            now = datetime.now()
            timestamps = [now - timedelta(minutes=i) for i in range(len(closes)-1, -1, -1)]
        
        # 创建图表
        fig = go.Figure(data=[go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name='K 线'
        )])
        
        # 添加移动平均线
        if len(closes) >= 20:
            ma20 = _calculate_ma(closes, 20)
            fig.add_trace(go.Scatter(
                x=timestamps,
                y=ma20,
                mode='lines',
                name='MA20',
                line=dict(color='#ffa726', width=1)
            ))
        
        # 更新布局
        fig.update_layout(
            title=title,
            xaxis_title="时间",
            yaxis_title="价格 (USD)",
            width=width,
            height=height,
            template='plotly_dark',
            xaxis_rangeslider_visible=False,
            margin=dict(l=50, r=50, t=50, b=50)
        )
        
        fig.update_xaxes(
            tickformat="%H:%M",
            tickangle=45
        )
        
        fig.update_yaxes(
            tickprefix="$",
            tickformat=".2f"
        )
        
        # 转换为 PNG
        img_bytes = pio.to_image(fig, format="png", width=width, height=height)
        
        return img_bytes
        
    except Exception as e:
        print(f"[ChartGenerator] 生成 K 线图失败：{e}")
        return None


def _calculate_ma(prices: List[float], period: int) -> List[float]:
    """计算移动平均"""
    ma = []
    for i in range(len(prices)):
        if i < period - 1:
            ma.append(None)
        else:
            ma.append(sum(prices[i-period+1:i+1]) / period)
    return ma


def encode_image_to_base64(img_bytes: bytes) -> str:
    """将图片编码为 base64 字符串"""
    return base64.b64encode(img_bytes).decode('utf-8')
