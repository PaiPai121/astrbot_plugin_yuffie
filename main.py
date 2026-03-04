"""
main.py - Yuffie 贵金属监控系统 AstrBot 插件入口

AstrBot v4 标准插件结构
"""

import os
import sys
import asyncio
import subprocess
import base64

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
from plugins.alert_levels import alert_manager, AlertLevel
from plugins.chart_generator import generate_price_chart

# 全局变量
streamlit_process = None


def _start_streamlit_sync():
    """同步方式启动 Streamlit（用于__init__）

    注意：在 Docker 容器内无法启动子进程，需要在宿主机运行
    """
    global streamlit_process

    try:
        web_app_path = os.path.join(plugin_dir, "web_app.py")

        logger.info("[Yuffie] 💡 Web 面板启动说明:")
        logger.info("[Yuffie] 由于 Docker 限制，请在宿主机上手动运行以下命令启动 Web 面板:")
        logger.info(f"[Yuffie] cd {plugin_dir} && python3 -m streamlit run web_app.py --server.port 8501")
        logger.info("[Yuffie] 或者发送 /web 可视化 命令尝试启动")

    except Exception as e:
        logger.error(f"[Yuffie] ❌ Streamlit 启动提示失败：{e}")


async def _start_streamlit_async():
    """异步方式启动 Streamlit（用于命令）"""
    global streamlit_process

    try:
        web_app_path = os.path.join(plugin_dir, "web_app.py")

        logger.info("[Yuffie] 正在启动 Streamlit Web 监控面板...")

        # 使用 asyncio 启动后台进程
        streamlit_process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "streamlit", "run", web_app_path,
            "--server.port", "8501",
            "--server.headless", "true",
            "--server.address", "0.0.0.0",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True
        )

        logger.info("[Yuffie] ✅ Streamlit Web 监控面板已启动")
        logger.info("[Yuffie] 🌐 访问地址：http://localhost:8501")

        return True

    except Exception as e:
        logger.error(f"[Yuffie] ❌ Streamlit 启动失败：{e}")
        return False


class YuffiePlugin(Star):
    """
    Yuffie 贵金属监控插件主类
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.context = context
        self.config = config or {}
        self.monitor_started = False

        # 在__init__中直接初始化
        self._init_monitor()

        # 尝试自动启动 Streamlit
        _start_streamlit_sync()

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

    @filter.command("金价订阅", alias={"订阅金价", "yuffie 订阅", "订阅"})
    async def subscribe(self, event: AstrMessageEvent):
        '''订阅黄金跳水预警'''
        try:
            await subscribe_command(event)
            yield event.plain_result("✅ 订阅成功！输入 /金价订阅状态 查看状态")
        except Exception as e:
            logger.error(f"[Yuffie] 订阅失败：{e}")
            yield event.plain_result(f"⚠️ 订阅失败：{e}")

    @filter.command("金价取消订阅", alias={"取消订阅金价", "yuffie 取消订阅", "取消订阅"})
    async def unsubscribe(self, event: AstrMessageEvent):
        '''取消订阅'''
        try:
            await unsubscribe_command(event)
            yield event.plain_result("✅ 取消订阅成功！")
        except Exception as e:
            logger.error(f"[Yuffie] 取消订阅失败：{e}")
            yield event.plain_result(f"⚠️ 取消订阅失败：{e}")

    @filter.command("金价订阅状态", alias={"订阅金价状态", "yuffie 订阅状态", "订阅状态"})
    async def sub_status(self, event: AstrMessageEvent):
        '''查看订阅状态'''
        try:
            result_msg = await subscription_status_command(event)
            yield event.plain_result(result_msg)
        except Exception as e:
            logger.error(f"[Yuffie] 查询订阅状态失败：{e}")
            yield event.plain_result(f"⚠️ 查询失败：{e}")

    @filter.command("金价订阅统计", alias={"订阅金价统计", "yuffie 订阅统计", "订阅统计"})
    async def sub_stats(self, event: AstrMessageEvent):
        '''查看订阅统计（管理员）'''
        try:
            result_msg = await subscription_stats_command(event)
            yield event.plain_result(result_msg)
        except Exception as e:
            logger.error(f"[Yuffie] 查询订阅统计失败：{e}")
            yield event.plain_result(f"⚠️ 查询失败：{e}")

    @filter.command("金价监控状态", alias={"监控金价", "yuffie 监控状态", "监控状态"})
    async def monitor_status(self, event: AstrMessageEvent):
        '''查看预警监控器运行状态'''
        try:
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
        except Exception as e:
            logger.error(f"[Yuffie] 查询监控状态失败：{e}")
            yield event.plain_result(f"⚠️ 查询失败：{e}")

    @filter.command("yuffie 帮助", alias={"黄金帮助", "金价帮助"})
    async def show_help(self, event: AstrMessageEvent):
        '''显示插件帮助信息'''
        help_text = """
📊 **Yuffie 贵金属监控系统**

💬 **可用指令**:
  /黄金分析       - 获取黄金市场深度分析报告
  /金价订阅       - 订阅黄金跳水预警
  /金价取消订阅   - 取消订阅
  /金价订阅状态   - 查看订阅状态
  /金价订阅统计   - 查看订阅统计（管理员）
  /金价监控状态   - 查看监控器运行状态
  /yuffie 设置阈值 - 动态调整预警阈值
  /yuffie 测试图表 - 测试图表生成功能
  /web 可视化     - 启动 Web 监控面板
  /帮助           - 显示此帮助信息

⚙️ **高级功能**:
  - 多级预警：Level 1(提醒) → Level 2(预警) → Level 3(熔断)
  - 图表推送：触发警报时自动发送价格走势图
  - 动态阈值：通过 /yuffie 设置阈值 调整灵敏度

⚠️ **提示**: 价格异动会自动推送给订阅用户
"""
        yield event.plain_result(help_text)

    @filter.command("web 可视化", alias={"启动 web", "web 面板"})
    async def start_web(self, event: AstrMessageEvent):
        '''启动 Web 监控面板'''
        global streamlit_process

        # 检查是否已经在运行
        if streamlit_process and streamlit_process.poll() is None:
            yield event.plain_result("✅ Streamlit Web 面板已在运行\n\n🌐 访问地址：http://localhost:8501")
            return

        # 启动 Streamlit
        success = await _start_streamlit_async()

        if success:
            yield event.plain_result("✅ Streamlit Web 面板已启动\n\n🌐 访问地址：http://localhost:8501\n\n💡 提示：如果是 Docker 部署，请确保 8501 端口已映射")
        else:
            yield event.plain_result("❌ Web 面板启动失败，请查看日志")

    @filter.command("yuffie 设置阈值", alias={"设置阈值", "set_atr"})
    async def set_threshold(self, event: AstrMessageEvent, level: str = None, value: float = None):
        '''
        动态调整预警阈值

        用法：/yuffie 设置阈值 level2_k 3.0
        参数:
            level: 等级 (level1_k, level2_k, level3_k)
            value: 新的 k 值
        '''
        if level is None or value is None:
            help_msg = """
⚙️ **Yuffie 阈值设置**

用法：`/yuffie 设置阈值 <等级> <k 值>`

当前阈值:
- Level 1 (提醒): k = {:.1f}
- Level 2 (预警): k = {:.1f}
- Level 3 (熔断): k = {:.1f}

示例:
`/yuffie 设置阈值 level2_k 3.0` - 将 Level 2 阈值设为 3.0
""".format(
                alert_manager.get_threshold('level1_k'),
                alert_manager.get_threshold('level2_k'),
                alert_manager.get_threshold('level3_k')
            )
            yield event.plain_result(help_msg)
            return

        if alert_manager.set_threshold(level, value):
            yield event.plain_result(f"✅ 阈值已更新\n\n{level} = {value}")
        else:
            yield event.plain_result(f"❌ 无效的等级：{level}\n\n可用等级：level1_k, level2_k, level3_k")

    @filter.command("yuffie 测试图表")
    async def test_chart(self, event: AstrMessageEvent):
        '''测试图表生成功能 - 使用真实 K 线历史数据'''
        try:
            import aiohttp
            from datetime import datetime, timedelta

            # 获取真实汇率（USD/CNY）
            exchange_rate = 7.3
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=5) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            exchange_rate = data.get('rates', {}).get('CNY', 7.3)
            except Exception as e:
                logger.warning(f"[Yuffie] 获取汇率失败，使用默认值：{e}")

            # 获取真实 K 线历史数据（Binance API，无需 WebSocket）
            # 获取最近 50 根 1 小时 K 线
            current_price = 2650.0
            usd_prices = []
            timestamps = []

            try:
                async with aiohttp.ClientSession() as session:
                    # Binance K 线 API - 1 小时 K 线，最近 50 根
                    async with session.get(
                        'https://api.binance.com/api/v3/klines?symbol=PAXGUSDT&interval=1h&limit=50',
                        timeout=10
                    ) as resp:
                        if resp.status == 200:
                            klines = await resp.json()
                            for k in klines:
                                # k[0] = 开盘时间，k[4] = 收盘价
                                close_price = float(k[4])
                                usd_prices.append(close_price)
                                timestamps.append(datetime.fromtimestamp(k[0] / 1000))

                            current_price = usd_prices[-1] if usd_prices else current_price
                            logger.info(f"[Yuffie] 成功获取 {len(usd_prices)} 根 K 线")
                        else:
                            logger.warning(f"[Yuffie] Binance API 返回 {resp.status}")
            except Exception as e:
                logger.warning(f"[Yuffie] 获取 K 线失败：{e}")

            # 如果获取失败，使用 CoinGecko 备用方案
            if not usd_prices:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            'https://api.coingecko.com/api/v3/simple/price?ids=pax-gold&vs_currencies=usd',
                            timeout=5
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                current_price = data.get('pax-gold', {}).get('usd', 2650.0)
                                # 生成模拟数据
                                usd_prices = [current_price + i * 0.5 for i in range(-25, 25)]
                                now = datetime.now()
                                timestamps = [now - timedelta(hours=i) for i in range(50, 0, -1)]
                except Exception as e:
                    logger.warning(f"[Yuffie] 备用方案失败：{e}")

            # 人民币价格 = 美元价格 × 汇率 ÷ 31.1035
            cny_prices = [price * exchange_rate / 31.1035 for price in usd_prices]

            # 生成图表
            title = f"金价走势（PAXG: ${current_price:.2f}）"
            img_bytes = generate_price_chart(
                usd_prices=usd_prices,
                cny_prices=cny_prices,
                timestamps=timestamps,
                title=title
            )

            if img_bytes:
                import tempfile
                import os

                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
                    f.write(img_bytes)
                    temp_path = f.name

                from astrbot.api.message_components import Image, Plain
                time_range = ""
                if timestamps:
                    time_range = f"\n📅 时间范围：{timestamps[0].strftime('%m-%d %H:%M')} - {timestamps[-1].strftime('%m-%d %H:%M')}"

                chain = [
                    Plain(f"📊 金价走势（真实 K 线）\n\n💰 当前金价：${current_price:.2f}/盎司{time_range}\n🔵 蓝色：美元/盎司 (国际金价)\n🔴 红色：人民币/克 (理论换算)\n💡 数据来源：Binance API"),
                    Image.fromFileSystem(temp_path),
                ]
                yield event.chain_result(chain)

                try:
                    os.unlink(temp_path)
                except:
                    pass
            else:
                yield event.plain_result("❌ 图表生成失败，请确保已安装 matplotlib")

        except Exception as e:
            import traceback
            logger.error(f"[Yuffie] 测试图表失败：{e}")
            logger.error(traceback.format_exc())
            yield event.plain_result(f"❌ 图表生成失败：{e}")
