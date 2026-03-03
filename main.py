"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口

AstrBot v4.x 标准插件结构
"""

import os
import sys
import asyncio
import subprocess
import atexit
import shlex
from typing import Optional

# 确保插件内部模块可以正常导入
sys.path.append(os.path.dirname(__file__))

# AstrBot API
from astrbot.api.all import *
from astrbot.api.message_components import Plain

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

# 全局变量
_streamlit_process = None


def _start_streamlit():
    """后台启动 Streamlit"""
    global _streamlit_process
    
    try:
        web_app_path = os.path.join(os.path.dirname(__file__), "web_app.py")
        
        logger.info(f"[Yuffie] 正在启动 Streamlit Web 监控面板...")
        
        # 启动 Streamlit（后台运行）
        _streamlit_process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", web_app_path,
             "--server.port", "8501",
             "--server.headless", "true",
             "--server.address", "0.0.0.0"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        
        logger.info("[Yuffie] ✅ Web 监控仪表盘已在后台启动")
        logger.info("[Yuffie] 🌐 访问地址：http://localhost:8501")
        
    except Exception as e:
        logger.error(f"[Yuffie] ❌ Web 仪表盘启动失败：{e}")


def _stop_streamlit():
    """停止 Streamlit"""
    global _streamlit_process
    
    if _streamlit_process:
        try:
            logger.info("[Yuffie] 正在停止 Streamlit...")
            _streamlit_process.terminate()
            _streamlit_process.wait(timeout=5)
            logger.info("[Yuffie] ✅ Streamlit 已停止")
        except Exception as e:
            logger.error(f"[Yuffie] 停止 Streamlit 失败：{e}")
            if _streamlit_process:
                _streamlit_process.kill()


# 注册退出处理
atexit.register(_stop_streamlit)


@register.plugin("astrbot_plugin_yuffie", "Yuffie 贵金属监控", "高可用贵金属高频监控与多因子分析系统", "1.0.0")
class YuffiePlugin(Star):
    """
    Yuffie 贵金属监控插件主类
    
    AstrBot v4.x 标准插件类
    """
    
    def __init__(self, context: Context, config: dict):
        super().__init__(context)
        self.config = config
        self.monitor_started = False
        logger.info(f"[Yuffie] 插件初始化完成")
    
    # 插件启用时自动调用
    async def on_enable(self, context: Context):
        """插件启用时调用"""
        logger.info(f"[Yuffie] 插件正在初始化...")
        
        # 启动 Streamlit Web 监控面板
        _start_streamlit()
        
        # 获取配置
        use_mock = self.config.get("use_mock", False)
        cooldown = self.config.get("cooldown_minutes", 30)
        
        # 初始化监控器
        init_monitor(use_mock=use_mock, cooldown_minutes=cooldown)
        
        # 定义警报回调
        async def send_alert(message: str, level: str):
            logger.info(f"[Yuffie] [警报] [{level}] {message[:100]}...")
            # 这里可以调用 context 发送消息给订阅用户
        
        # 启动监控器
        await start_monitor(send_alert)
        self.monitor_started = True
        
        logger.info("[Yuffie] ✅ 后台监控已启动")
        logger.info("[Yuffie] 💬 可用指令：/订阅、/黄金分析、/订阅状态、/订阅统计")
    
    # 插件禁用时自动调用
    async def on_disable(self, context: Context):
        """插件禁用时调用"""
        logger.info(f"[Yuffie] 插件正在销毁...")
        
        # 停止 Streamlit
        _stop_streamlit()
        
        # 停止监控器
        await stop_monitor()
        self.monitor_started = False
        
        logger.info("[Yuffie] 插件已禁用")
    
    # 指令注册
    @register.command("黄金分析")
    async def gold_analysis(self, event: AstrMessageEvent):
        """
        /黄金分析 - 获取黄金市场深度分析报告
        """
        try:
            report = await handle_gold_analysis(event)
            yield event.plain_result(report)
        except Exception as e:
            yield event.plain_result(f"⚠️ 分析失败：{e}")
    
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
                yield event.plain_result("⚠️ 监控器未初始化")
                return
            
            status = monitor.get_status()
            
            # 构建状态消息
            status_msg = (
                f"📊 **Yuffie 监控器状态**\n\n"
                f"运行状态：{'🟢 运行中' if status['is_running'] else '🔴 已停止'}\n"
                f"Web 面板：http://localhost:8501\n"
                f"处理 Tick 数：{status['tick_count']}\n"
                f"触发警报数：{status['alert_count']}\n"
                f"滑窗大小：{status['window_size']}\n"
            )
            
            # 死信队列状态
            dlq = status.get('dlq_stats', {})
            if dlq:
                status_msg += (
                    f"\n📬 **死信队列**\n"
                    f"待处理：{dlq.get('pending_count', 0)}\n"
                    f"总重试：{dlq.get('total_retries', 0)}\n"
                )
            
            # 订阅用户统计
            subs = status.get('subscribers', {})
            if subs:
                status_msg += (
                    f"\n👥 **订阅用户**\n"
                    f"活跃用户：{subs.get('total_active', 0)}\n"
                    f"总用户：{subs.get('total_users', 0)}\n"
                    f"累计推送：{subs.get('total_alerts', 0)}\n"
                )
            
            yield event.plain_result(status_msg)
            
        except Exception as e:
            yield event.plain_result(f"⚠️ 查询失败：{e}")
