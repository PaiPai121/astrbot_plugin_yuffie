"""
plugins - Yuffie 贵金属监控系统业务插件层

包含:
    - alert_monitor: 极速预警插件（后台常驻任务，支持订阅推送）
    - analysis_report: 深度分析插件（响应用户指令）
    - subscriber_manager: 订阅用户管理
    - subscription_commands: 订阅管理指令
"""

from .alert_monitor import (
    AlertMonitor,
    get_monitor,
    init_monitor,
    start_monitor,
    stop_monitor
)

from .analysis_report import (
    AnalysisReport,
    handle_gold_analysis
)

from .subscriber_manager import SubscriberManager

from .subscription_commands import (
    subscribe_command,
    unsubscribe_command,
    subscription_status_command,
    subscription_stats_command
)

__all__ = [
    # Alert Monitor
    "AlertMonitor",
    "get_monitor",
    "init_monitor",
    "start_monitor",
    "stop_monitor",

    # Analysis Report
    "AnalysisReport",
    "handle_gold_analysis",

    # Subscriber Manager
    "SubscriberManager",

    # Subscription Commands
    "subscribe_command",
    "unsubscribe_command",
    "subscription_status_command",
    "subscription_stats_command"
]
