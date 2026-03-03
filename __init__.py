"""
astrbot_plugin_yuffie - Yuffie 贵金属高频监控与多因子分析系统

AstrBot 插件，提供：
- 实时金价监控
- 自动报警系统
- Web 监控面板
- 订阅管理
"""

from .main import YuffiePlugin

__all__ = ["YuffiePlugin"]
__version__ = "1.0.0"
