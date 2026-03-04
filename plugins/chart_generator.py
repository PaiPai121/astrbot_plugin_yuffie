"""
chart_generator.py - 图表生成（使用 matplotlib，无需 Chrome）

实现:
    - 使用 matplotlib 生成价格走势图
    - 支持保存为 PNG 图片
"""

import io
import base64
from typing import Optional, List
from datetime import datetime, timedelta

try:
    import matplotlib
    matplotlib.use('Agg')  # 非交互式后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter

    # 配置中文字体
    plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'SimHei', 'DejaVu Sans']
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    FuncFormatter = None


def generate_price_chart(
    prices: List[float],
    timestamps: Optional[List[datetime]] = None,
    title: str = "金价走势",
    width: int = 10,
    height: int = 5,
    dpi: int = 100
) -> Optional[bytes]:
    """
    生成价格走势图（PNG 图片）- 使用 matplotlib
    
    Args:
        prices: 价格列表
        timestamps: 时间戳列表（可选）
        title: 图表标题
        width: 宽度（英寸）
        height: 高度（英寸）
        dpi: 分辨率
    
    Returns:
        bytes: PNG 图片数据
    """
    if not MATPLOTLIB_AVAILABLE:
        print("[ChartGenerator] Matplotlib 未安装")
        return None
    
    try:
        # 创建时间轴
        if timestamps is None:
            now = datetime.now()
            timestamps = [now - timedelta(minutes=i) for i in range(len(prices)-1, -1, -1)]
        
        # 创建图表
        fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
        
        # 设置深色背景
        fig.patch.set_facecolor('#1e1e1e')
        ax.set_facecolor('#2d2d2d')
        
        # 添加价格线
        ax.plot(timestamps, prices, color='#29b6f6', linewidth=2, label='价格')
        
        # 填充下方区域
        ax.fill_between(timestamps, prices, min(prices), alpha=0.1, color='#29b6f6')
        
        # 添加移动平均线（如果数据足够）
        if len(prices) >= 20:
            ma20 = _calculate_ma(prices, 20)
            ax.plot(timestamps, ma20, color='#ffa726', linewidth=1, linestyle='--', label='MA20')
        
        # 设置标题和标签
        ax.set_title(title, color='white', fontsize=14, pad=10)
        ax.set_xlabel("时间", color='white', fontsize=10)
        ax.set_ylabel("价格 (USD)", color='white', fontsize=10)
        
        # 设置坐标轴颜色
        ax.tick_params(colors='white', which='both')
        for spine in ax.spines.values():
            spine.set_color('#444444')
        
        # 格式化 x 轴时间
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', color='white')
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.2f}'))
        
        # 添加图例
        ax.legend(loc='upper left', facecolor='#2d2d2d', edgecolor='#444444', 
                 labelcolor='white', fontsize=9)
        
        # 添加网格
        ax.grid(True, alpha=0.2, color='#666666', linestyle='-')
        
        # 自动调整布局
        plt.tight_layout()
        
        # 保存到 bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=dpi, facecolor=fig.get_facecolor(), 
                   edgecolor='none', bbox_inches='tight')
        buf.seek(0)
        img_bytes = buf.getvalue()
        plt.close(fig)
        
        return img_bytes
        
    except Exception as e:
        import traceback
        print(f"[ChartGenerator] 生成图表失败：{e}")
        print(traceback.format_exc())
        return None


def _calculate_ma(prices: List[float], period: int) -> List[Optional[float]]:
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
