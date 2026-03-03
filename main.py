"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口

这是 AstrBot 识别插件所需的标准入口文件。
AstrBot 会加载此文件并注册插件。

功能:
    1. 注册 /黄金分析 指令
    2. 启动后台预警监控任务
    3. 提供插件状态查询指令
    4. 自动启动 Streamlit Web 监控面板
"""

import asyncio
import subprocess
import atexit
import os
import sys
import shlex
from typing import Optional

# AstrBot API
try:
    from astrbot.api import logger, AstrBotConfig
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.message_components import Plain
    from astrbot.api.register import register
    from astrbot.api.platform import EventType
    ASTRBOT_AVAILABLE = True
except ImportError:
    # 开发环境模拟
    import logging
    logger = logging.getLogger("Yuffie")
    ASTRBOT_AVAILABLE = False

    class register:
        @staticmethod
        def command(*args, **kwargs):
            def decorator(func):
                return func
            return decorator

        @staticmethod
        def event_handler(*args, **kwargs):
            def decorator(func):
                return func
            return decorator

    class EventType:
        GroupMessage = 1
        FriendMessage = 2

    class AstrMessageEvent:
        pass

# 核心组件 - 使用绝对导入
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
except ImportError:
    # 如果导入失败，尝试从当前目录导入
    import plugins
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
_monitor_started = False

# 插件元数据
PLUGIN_NAME = "Yuffie 贵金属监控"
PLUGIN_VERSION = "1.0.0"
PLUGIN_AUTHOR = "Yuffie Team"
PLUGIN_DESCRIPTION = "高可用贵金属高频监控与多因子分析系统"


# ==================== 插件生命周期 ====================

async def start_plugin():
    """
    启动插件
    
    功能:
        1. 启动 Streamlit Web 监控面板（后台）
        2. 启动预警监控任务
    """
    global _monitor_started, _streamlit_process
    
    if _monitor_started:
        logger.warning("[Yuffie] 插件已启动，跳过")
        return
    
    # ==================== 自动启动 Streamlit 网页 ====================
    try:
        # 获取 web_app.py 的绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        web_app_path = os.path.join(current_dir, "web_app.py")
        
        # 构造启动命令 (使用当前 Python 环境运行 streamlit)
        # --server.headless=true 确保在服务器上运行时不会尝试打开浏览器
        cmd = f"{sys.executable} -m streamlit run \"{web_app_path}\" --server.port 8501 --server.headless=true --server.address 0.0.0.0"
        args = shlex.split(cmd)
        
        # 后台启动进程
        _streamlit_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            start_new_session=True  # 确保独立运行
        )
        
        logger.info("[Yuffie] ✅ Web 监控仪表盘已在后台启动")
        logger.info("[Yuffie] 🌐 访问地址：http://localhost:8501")
        
    except Exception as e:
        logger.error(f"[Yuffie] ❌ Web 仪表盘启动失败：{e}")
    # ================================================================
    
    # 原有的启动监控逻辑
    async def send_alert(message: str, level: str):
        """警报推送回调"""
        logger.info(f"[Yuffie] [警报] [{level}] {message[:100]}...")
        
        # 推送给所有订阅用户
        monitor = get_monitor()
        if monitor and monitor._send_alert_callback:
            await monitor._send_alert_callback(message)
    
    await start_monitor(send_alert)
    _monitor_started = True
    
    logger.info("[Yuffie] ✅ 后台监控已启动")
    logger.info("[Yuffie] 💬 可用指令：/订阅、/黄金分析、/订阅状态、/订阅统计")


async def stop_plugin():
    """
    插件停止函数（AstrBot 关闭时调用）
    """
    global _monitor_started, _streamlit_process
    
    logger.info("[Yuffie] 正在停止插件...")
    
    # 停止 Streamlit
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
    
    # 停止监控器
    await stop_monitor()
    _monitor_started = False
    
    logger.info("[Yuffie] 插件已停止")


def on_load():
    """插件加载时调用"""
    logger.info(f"[Yuffie] 插件加载中... {PLUGIN_NAME} v{PLUGIN_VERSION}")


def on_enable():
    """插件启用时调用"""
    logger.info(f"[Yuffie] 插件已启用")
    asyncio.create_task(start_plugin())


def on_disable():
    """插件禁用时调用"""
    logger.info(f"[Yuffie] 插件已禁用")
    asyncio.create_task(stop_plugin())


# ==================== AstrBot 指令注册 ====================

if ASTRBOT_AVAILABLE:

    @register.command("黄金分析", description="获取黄金市场深度分析报告", alias=["gold", "goldanalysis"])
    async def gold_analysis(event: AstrMessageEvent):
        """
        /黄金分析 - 获取黄金市场深度分析报告

        示例:
            /黄金分析
        """
        logger.info(f"[Yuffie] 收到黄金分析请求 from {event.get_sender_name()}")

        try:
            report = await handle_gold_analysis(event)
            await event.send(Plain(report))

        except Exception as e:
            logger.error(f"[Yuffie] 黄金分析失败：{e}")
            await event.send(Plain(f"⚠️ 分析失败：{e}"))

    @register.command("订阅", description="订阅黄金跳水预警", alias=["subscribe"])
    async def subscribe(event: AstrMessageEvent):
        """
        /订阅 - 订阅黄金跳水预警

        示例:
            /订阅
        """
        logger.info(f"[Yuffie] 收到订阅请求 from {event.get_sender_name()}")
        await subscribe_command(event)

    @register.command("取消订阅", description="取消黄金跳水预警订阅", alias=["unsubscribe"])
    async def unsubscribe(event: AstrMessageEvent):
        """
        /取消订阅 - 取消订阅

        示例:
            /取消订阅
        """
        logger.info(f"[Yuffie] 收到取消订阅请求 from {event.get_sender_name()}")
        await unsubscribe_command(event)

    @register.command("订阅状态", description="查看订阅状态", alias=["status"])
    async def sub_status(event: AstrMessageEvent):
        """
        /订阅状态 - 查看订阅状态

        示例:
            /订阅状态
        """
        logger.info(f"[Yuffie] 收到订阅状态查询 from {event.get_sender_name()}")
        await subscription_status_command(event)

    @register.command("订阅统计", description="查看订阅统计（管理员）", alias=["stats"])
    async def sub_stats(event: AstrMessageEvent):
        """
        /订阅统计 - 查看订阅统计

        示例:
            /订阅统计
        """
        logger.info(f"[Yuffie] 收到订阅统计查询 from {event.get_sender_name()}")
        await subscription_stats_command(event)

    @register.command("监控状态", description="查看监控器状态", alias=["ystatus"])
    async def monitor_status(event: AstrMessageEvent):
        """
        /监控状态 - 查看监控器运行状态

        示例:
            /监控状态
        """
        logger.info(f"[Yuffie] 收到监控状态查询 from {event.get_sender_name()}")

        try:
            monitor = get_monitor()

            if not monitor:
                await event.send(Plain("⚠️ 监控器未初始化"))
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

            await event.send(Plain(status_msg))

        except Exception as e:
            logger.error(f"[Yuffie] 监控状态查询失败：{e}")
            await event.send(Plain(f"⚠️ 查询失败：{e}"))


# ==================== 插件主类 ====================

class YuffiePlugin:
    """
    Yuffie 贵金属监控插件主类

    AstrBot 会自动加载这个类并调用其方法
    """

    def __init__(self, context: dict, config: dict):
        """
        插件初始化

        Args:
            context: AstrBot 上下文
            config: 插件配置
        """
        self.context = context
        self.config = config
        logger.info(f"[Yuffie] 插件初始化完成")

    async def initialize(self):
        """插件初始化时调用（异步）"""
        logger.info(f"[Yuffie] 插件正在初始化...")
        await start_plugin()

    async def destroy(self):
        """插件销毁时调用（异步）"""
        logger.info(f"[Yuffie] 插件正在销毁...")
        await stop_plugin()


# ==================== 主程序入口 ====================

if __name__ == "__main__":
    """
    独立运行测试（非 AstrBot 环境）
    """

    async def test_send_alert(message: str, level: str):
        print(f"[警报] [{level}] {message}")

    async def main():
        print(f"=== {PLUGIN_NAME} v{PLUGIN_VERSION} ===\n")

        # 初始化
        init_plugin({"use_mock": True, "cooldown_minutes": 5})

        # 启动
        await start_plugin()

        # 测试警报发送
        await test_send_alert("这是一条测试警报", "normal")
        print(f"状态：{get_monitor().get_status()}")

        # 运行 10 秒
        await asyncio.sleep(10)

        # 停止
        await stop_plugin()

        print("\n测试完成")

    asyncio.run(main())
