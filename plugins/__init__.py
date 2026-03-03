"""
plugins/__init__.py - Yuffie 插件包初始化
"""

# 导出所有公共组件
from .alert_monitor import init_monitor, start_monitor, stop_monitor, get_monitor
from .analysis_report import handle_gold_analysis
from .subscription_commands import (
    subscribe_command,
    unsubscribe_command,
    subscription_status_command,
    subscription_stats_command
)

__all__ = [
    "init_monitor",
    "start_monitor", 
    "stop_monitor",
    "get_monitor",
    "handle_gold_analysis",
    "subscribe_command",
    "unsubscribe_command",
    "subscription_status_command",
    "subscription_stats_command"
]
