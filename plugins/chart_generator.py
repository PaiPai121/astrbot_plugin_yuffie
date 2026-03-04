"""
chart_generator.py - 图表生成（使用 matplotlib，支持中文）

实现:
    - 使用 matplotlib 生成价格走势图
    - 支持中文显示
    - 同时显示美元和人民币价格
"""

import io
from typing import Optional, List
from datetime import datetime, timedelta

try:
    import matplotlib
    matplotlib.use('Agg')  # 非交互式后端
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.ticker import FuncFormatter
    
    # 配置中文字体 - 使用文泉驿字体
    plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'WenQuanYi Zen Hei', 'SimHei', 'Arial Unicode MS']
    plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
    
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    plt = None
    FuncFormatter = None


def generate_price_chart(
    usd_prices: List[float],
    cny_prices: Optional[List[float]] = None,
    timestamps: Optional[List[datetime]] = None,
    title: str = "金价走势",
    width: int = 12,
    height: int = 6,
    dpi: int = 100
) -> Optional[bytes]:
    """
    生成价格走势图（PNG 图片）- 使用 matplotlib
    
    Args:
        usd_prices: 美元价格列表
        cny_prices: 人民币价格列表（可选）
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
            timestamps = [now - timedelta(minutes=i) for i in range(len(usd_prices)-1, -1, -1)]
        
        # 创建图表 - 双 Y 轴
        fig, ax1 = plt.subplots(figsize=(width, height), dpi=dpi)
        
        # 设置深色背景
        fig.patch.set_facecolor('#1e1e1e')
        ax1.set_facecolor('#2d2d2d')
        
        # 添加美元价格线（左 Y 轴）
        line1 = ax1.plot(timestamps, usd_prices, color='#29b6f6', linewidth=2, label='美元/盎司')
        ax1.fill_between(timestamps, usd_prices, min(usd_prices), alpha=0.1, color='#29b6f6')
        ax1.set_ylabel('美元/盎司', color='#29b6f6', fontsize=12)
        ax1.tick_params(axis='y', labelcolor='#29b6f6')
        
        # 添加人民币价格线（右 Y 轴）
        if cny_prices and len(cny_prices) == len(usd_prices):
            ax2 = ax1.twinx()
            line2 = ax2.plot(timestamps, cny_prices, color='#ff6b6b', linewidth=2, label='人民币/克')
            ax2.fill_between(timestamps, cny_prices, min(cny_prices), alpha=0.1, color='#ff6b6b')
            ax2.set_ylabel('人民币/克', color='#ff6b6b', fontsize=12)
            ax2.tick_params(axis='y', labelcolor='#ff6b6b')
        
        # 设置标题和标签
        ax1.set_title(title, color='white', fontsize=14, pad=10)
        ax1.set_xlabel("时间", color='white', fontsize=11)
        
        # 设置坐标轴颜色
        ax1.tick_params(colors='white', which='both')
        for spine in ax1.spines.values():
            spine.set_color('#444444')
        
        # 格式化 x 轴时间
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right', color='white')
        
        # 格式化 Y 轴
        ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.0f}'))
        if cny_prices:
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'¥{x:.0f}'))
        
        # 添加图例
        lines1, labels1 = ax1.get_legend_handles_labels()
        if cny_prices:
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left', 
                      facecolor='#2d2d2d', edgecolor='#444444', labelcolor='white', fontsize=10)
        else:
            ax1.legend(loc='upper left', facecolor='#2d2d2d', edgecolor='#444444', 
                      labelcolor='white', fontsize=10)
        
        # 添加网格
        ax1.grid(True, alpha=0.2, color='#666666', linestyle='-')
        
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


def encode_image_to_base64(img_bytes: bytes) -> str:
    """将图片编码为 base64 字符串"""
    return base64.b64encode(img_bytes).decode('utf-8')
