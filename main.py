"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口
"""

import os
import sys

# 确保插件内部模块可以正常导入
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)
    sys.path.insert(0, os.path.join(plugin_dir, 'plugins'))
    sys.path.insert(0, os.path.join(plugin_dir, 'core'))

# AstrBot API
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.register import register
from astrbot.api.star import Context, Star, Register

# 核心组件
from plugins.alert_monitor import (
    init_monitor,
    start_monitor,
    stop_monitor,
    get_monitor
)
from plugins.analysis_report import handle_gold_analysis
from plugins.subscription_commands import (
    subscribe_command,
    unsubscribe_command,
    subscription_status_command,
    subscription_stats_command
)


# 插件主类
class YuffiePlugin(Star):
    """
    Yuffie 贵金属监控插件主类
    """
    
    def __init__(self, context: Context, config: dict):
        super().__init__(context, config)
        self.context = context
        self.config = config
        self.monitor_started = False
        logger.info("[Yuffie] 插件初始化完成")
    
    async def initialize(self):
        """插件初始化时调用"""
        logger.info("[Yuffie] 插件正在初始化...")
        
        # 获取配置
        use_mock = self.config.get("use_mock", False)
        cooldown = self.config.get("cooldown_minutes", 30)
        
        # 初始化监控器
        try:
            init_monitor(use_mock=use_mock, cooldown_minutes=cooldown)
            
            # 定义警报回调
            async def send_alert(message: str, level: str):
                logger.info(f"[Yuffie] [警报] [{level}] {message[:100]}...")
            
            # 启动监控器
            await start_monitor(send_alert)
            self.monitor_started = True
            
            logger.info("[Yuffie] ✅ 后台监控已启动")
            logger.info("[Yuffie] 💬 可用指令：/订阅、/黄金分析、/订阅状态、/订阅统计")
            
        except Exception as e:
            logger.error(f"[Yuffie] 启动监控器失败：{e}")
    
    async def destroy(self):
        """插件销毁时调用"""
        logger.info("[Yuffie] 插件正在销毁...")
        
        try:
            await stop_monitor()
            self.monitor_started = False
            logger.info("[Yuffie] 插件已禁用")
        except Exception as e:
            logger.error(f"[Yuffie] 停止监控器失败：{e}")
    
    # 指令注册
    @register.command("黄金分析")
    async def gold_analysis(self, event: AstrMessageEvent):
        """
        /黄金分析 - 获取黄金市场深度分析报告
        """
        try:
            report = await handle_gold_analysis(event)
            await event.send(Plain(report))
        except Exception as e:
            await event.send(Plain(f"⚠️ 分析失败：{e}"))
    
    @register.command("订阅")
    async def subscribe(self, event: AstrMessageEvent):
        """
        /订阅 - 订阅黄金跳水预警
        """
        await subscribe_command(event)
    
    @register.command("取消订阅")
    async def unsubscribe(self, event: AstrMessageEvent):
        """
        /取消订阅 - 取消订阅
        """
        await unsubscribe_command(event)
    
    @register.command("订阅状态")
    async def sub_status(self, event: AstrMessageEvent):
        """
        /订阅状态 - 查看订阅状态
        """
        await subscription_status_command(event)
    
    @register.command("订阅统计")
    async def sub_stats(self, event: AstrMessageEvent):
        """
        /订阅统计 - 查看订阅统计（管理员）
        """
        await subscription_stats_command(event)
    
    @register.command("监控状态")
    async def monitor_status(self, event: AstrMessageEvent):
        """
        /监控状态 - 查看监控器运行状态
        """
        try:
            monitor = get_monitor()
            
            if not monitor:
                await event.send(Plain("⚠️ 监控器未初始化"))
                return
            
            status = monitor.get_status()
            
            status_msg = (
                f"📊 **Yuffie 监控器状态**\n\n"
                f"运行状态：{'🟢 运行中' if status['is_running'] else '🔴 已停止'}\n"
                f"处理 Tick 数：{status['tick_count']}\n"
                f"触发警报数：{status['alert_count']}\n"
            )
            
            await event.send(Plain(status_msg))
            
        except Exception as e:
            await event.send(Plain(f"⚠️ 查询失败：{e}"))


# 注册插件 - 这是关键！
Register.register_star(YuffiePlugin)
