"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口

AstrBot v4 标准插件结构
"""

import os
import sys
import asyncio
import subprocess

# 确保插件内部模块可以被正常导入
plugin_dir = os.path.dirname(os.path.abspath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

# AstrBot API
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import logger

# 导入插件组件
from plugins import (
    init_monitor,
    start_monitor,
    stop_monitor,
    get_monitor,
    handle_gold_analysis,
    subscribe_command,
    unsubscribe_command,
    subscription_status_command,
    subscription_stats_command
)


class YuffiePlugin(Star):
    """
    Yuffie 贵金属监控插件主类
    """
    
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        self.monitor_started = False
        self.streamlit_process = None
        
        # 在__init__中直接初始化
        self._init_monitor()
        self._start_streamlit()
    
    def _init_monitor(self):
        """初始化监控器"""
        logger.info("[Yuffie] 插件正在初始化...")
        
        # 从配置中读取参数
        use_mock = self.config.get("use_mock", False)
        cooldown = self.config.get("cooldown_minutes", 30)
        
        try:
            # 初始化监控器
            init_monitor(use_mock=use_mock, cooldown_minutes=cooldown)
            
            # 定义警报发送回调
            async def send_alert(message: str, level: str):
                logger.info(f"[Yuffie Alert] {level}: {message}")
            
            # 启动后台异步监控任务
            asyncio.create_task(start_monitor(send_alert))
            self.monitor_started = True
            
            logger.info("[Yuffie] ✅ 后台监控已启动")
            logger.info("[Yuffie] 💬 可用指令：/黄金分析、/订阅、/取消订阅、/订阅状态、/订阅统计、/监控状态")
            
        except Exception as e:
            logger.error(f"[Yuffie] 启动监控器失败：{e}")
    
    def _start_streamlit(self):
        """启动 Streamlit Web 面板"""
        try:
            web_app_path = os.path.join(plugin_dir, "web_app.py")
            
            logger.info("[Yuffie] 正在启动 Streamlit Web 监控面板...")
            
            # 启动 Streamlit 进程（后台运行）
            self.streamlit_process = subprocess.Popen(
                [sys.executable, "-m", "streamlit", "run", web_app_path,
                 "--server.port", "8501",
                 "--server.headless", "true",
                 "--server.address", "0.0.0.0"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            
            logger.info("[Yuffie] ✅ Streamlit Web 监控面板已启动")
            logger.info("[Yuffie] 🌐 访问地址：http://localhost:8501")
            
        except Exception as e:
            logger.error(f"[Yuffie] ❌ Streamlit 启动失败：{e}")
    
    def __del__(self):
        """插件销毁时清理资源"""
        if self.streamlit_process:
            try:
                self.streamlit_process.terminate()
                logger.info("[Yuffie] Streamlit 已停止")
            except Exception:
                pass
    
    # 注册指令：使用 @filter.command 装饰类方法
    @filter.command("黄金分析")
    async def gold_analysis(self, event: AstrMessageEvent):
        '''获取黄金市场深度分析报告'''
        try:
            report = await handle_gold_analysis(event)
            yield event.plain_result(report)
        except Exception as e:
            logger.error(f"[Yuffie] 黄金分析失败：{e}")
            yield event.plain_result(f"⚠️ 分析失败：{e}")

    @filter.command("订阅")
    async def subscribe(self, event: AstrMessageEvent):
        '''订阅黄金跳水预警'''
        await subscribe_command(event)
        yield event.plain_result("✅ 订阅成功！输入 /订阅状态 查看状态")

    @filter.command("取消订阅")
    async def unsubscribe(self, event: AstrMessageEvent):
        '''取消订阅'''
        await unsubscribe_command(event)
        yield event.plain_result("✅ 取消订阅成功！")

    @filter.command("订阅状态")
    async def sub_status(self, event: AstrMessageEvent):
        '''查看订阅状态'''
        await subscription_status_command(event)

    @filter.command("订阅统计")
    async def sub_stats(self, event: AstrMessageEvent):
        '''查看订阅统计（管理员）'''
        await subscription_stats_command(event)

    @filter.command("监控状态")
    async def monitor_status(self, event: AstrMessageEvent):
        '''查看预警监控器运行状态'''
        monitor = get_monitor()
        if not monitor:
            yield event.plain_result("⚠️ 监控器未初始化")
            return
            
        status = monitor.get_status()
        status_msg = (
            f"📊 **Yuffie 监控器状态**\n\n"
            f"运行状态：{'🟢 运行中' if status['is_running'] else '🔴 已停止'}\n"
            f"处理 Tick：{status.get('tick_count', 0)}\n"
            f"触发警报：{status.get('alert_count', 0)}"
        )
        yield event.plain_result(status_msg)

    @filter.command("yuffie 帮助")
    async def show_help(self, event: AstrMessageEvent):
        '''显示插件帮助信息'''
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
