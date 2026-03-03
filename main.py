"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口

参考 BiliVideo 插件结构
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
from astrbot.api import logger, filter
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star


# 核心组件
try:
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
except ImportError as e:
    logger.error(f"[Yuffie] 导入核心组件失败：{e}")


class YuffiePlugin(Star):
    """
    Yuffie 贵金属监控插件主类
    """
    
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
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
            logger.info("[Yuffie] 💬 可用指令：/黄金分析、/订阅、/取消订阅、/订阅状态、/订阅统计")
            
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
    
    # ==================== 指令注册 ====================
    
    @filter.command("黄金分析", alias={"gold", "goldanalysis"})
    async def gold_analysis(self, event: AstrMessageEvent):
        """
        /黄金分析 - 获取黄金市场深度分析报告
        """
        try:
            report = await handle_gold_analysis(event)
            yield event.plain_result(report)
        except Exception as e:
            yield event.plain_result(f"⚠️ 分析失败：{e}")
    
    @filter.command("订阅", alias={"subscribe"})
    async def subscribe(self, event: AstrMessageEvent):
        """
        /订阅 - 订阅黄金跳水预警
        """
        await subscribe_command(event)
        yield event.plain_result("✅ 订阅成功！输入 /订阅状态 查看状态")
    
    @filter.command("取消订阅", alias={"unsubscribe"})
    async def unsubscribe(self, event: AstrMessageEvent):
        """
        /取消订阅 - 取消订阅
        """
        await unsubscribe_command(event)
        yield event.plain_result("✅ 取消订阅成功！")
    
    @filter.command("订阅状态", alias={"status"})
    async def sub_status(self, event: AstrMessageEvent):
        """
        /订阅状态 - 查看订阅状态
        """
        await subscription_status_command(event)
    
    @filter.command("订阅统计", alias={"stats"})
    async def sub_stats(self, event: AstrMessageEvent):
        """
        /订阅统计 - 查看订阅统计（管理员）
        """
        await subscription_stats_command(event)
    
    @filter.command("监控状态", alias={"ystatus"})
    async def monitor_status(self, event: AstrMessageEvent):
        """
        /监控状态 - 查看监控器运行状态
        """
        try:
            monitor = get_monitor()
            
            if not monitor:
                yield event.plain_result("⚠️ 监控器未初始化")
                return
            
            status = monitor.get_status()
            
            status_msg = (
                f"📊 **Yuffie 监控器状态**\n\n"
                f"运行状态：{'🟢 运行中' if status['is_running'] else '🔴 已停止'}\n"
                f"处理 Tick 数：{status['tick_count']}\n"
                f"触发警报数：{status['alert_count']}\n"
                f"滑窗大小：{status['window_size']}\n"
            )
            
            yield event.plain_result(status_msg)
            
        except Exception as e:
            yield event.plain_result(f"⚠️ 查询失败：{e}")
    
    @filter.command("yuffie 帮助", alias={"yuffiehelp", "帮助"})
    async def show_help(self, event: AstrMessageEvent):
        """
        显示插件帮助信息
        """
        help_text = """
📊 **Yuffie 贵金属监控系统**

💬 **可用指令**:
  /黄金分析     - 获取黄金市场深度分析报告
  /订阅         - 订阅黄金跳水预警
  /取消订阅     - 取消订阅
  /订阅状态     - 查看订阅状态
  /订阅统计     - 查看订阅统计（管理员）
  /监控状态     - 查看监控器运行状态
  /帮助         - 显示此帮助信息

🌐 **Web 面板**: http://localhost:8501

⚠️ **提示**: 价格异动会自动推送给订阅用户
"""
        yield event.plain_result(help_text)
