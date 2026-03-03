"""
alert_monitor.py - 极速预警插件（支持订阅用户推送）

职责:
    1. 后台常驻任务，实时监控价格异动
    2. 工作流：启动 DataStream -> 遇到新价格 -> 调用 market_cal 确认非休市 
       -> 调用 indicators 计算是否触发阈值 -> 若触发，调用 state_manager 写入冷却期 
       -> 发送预警给所有订阅用户
    3. 捕获 CircuitBreakerException 并发送严重的系统报警
"""

import asyncio
import time
from datetime import datetime
from typing import Optional, Dict, Any, List, Callable

# AstrBot 导入
try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger("Yuffie")

# 核心组件导入
from core.data_stream import (
    create_data_stream,
    HighFrequencyDataStream,
    MockDataStream,
    TickData,
    CircuitBreakerException
)
from core.market_cal import MarketCalendar
from core.indicators import (
    check_abnormal_volatility,
    calculate_atr_from_ticks,
    load_config
)
from core.state_manager import StateManager
from .subscriber_manager import SubscriberManager


class AlertMonitor:
    """
    极速预警监控器（支持订阅用户推送）
    
    核心功能:
        1. 启动后台数据流监控
        2. 实时检测异常波动
        3. 发送预警消息给所有订阅用户
        4. 处理系统熔断报警
    """
    
    def __init__(
        self,
        use_mock: bool = False,
        cooldown_minutes: int = 30,
        window_size: int = 60
    ):
        """
        初始化预警监控器
        
        Args:
            use_mock: 是否使用模拟数据（测试用）
            cooldown_minutes: 预警冷却时间（分钟）
            window_size: 滑窗大小（Tick 数量）
        """
        self.use_mock = use_mock
        self.cooldown_minutes = cooldown_minutes
        self.window_size = window_size
        
        # 核心组件
        self.stream: Optional[HighFrequencyDataStream] = None
        self.market_cal: Optional[MarketCalendar] = None
        self.state_mgr: Optional[StateManager] = None
        self.subscriber_mgr: Optional[SubscriberManager] = None
        
        # 配置
        self.config = load_config()
        
        # 运行状态
        self._is_running = False
        self._background_task: Optional[asyncio.Task] = None
        
        # 统计
        self._tick_count = 0
        self._alert_count = 0
        self._last_alert_time = 0.0
        
        # 推送回调（由 AstrBot 设置）
        self._send_alert_callback: Optional[Callable] = None
        
        logger.info(f"[AlertMonitor] 初始化完成：mock={use_mock}, cooldown={cooldown_minutes}min")
    
    def set_send_alert_callback(self, callback: Callable):
        """
        设置报警发送回调
        
        Args:
            callback: 异步函数 async def callback(user_id: str, message: str)
        """
        self._send_alert_callback = callback
        logger.info("[AlertMonitor] 报警推送回调已设置")
    
    def start(self):
        """启动监控器"""
        self._is_running = True
        
        # 初始化组件
        self.stream = create_data_stream(
            use_mock=self.use_mock,
            max_window_size=self.window_size
        )
        self.market_cal = MarketCalendar()
        self.state_mgr = StateManager()
        self.subscriber_mgr = SubscriberManager()
        
        # 注册 Tick 回调
        def on_tick(tick: TickData):
            asyncio.create_task(self._handle_tick(tick))
        
        self.stream.register_callback(on_tick)
        
        # 启动数据流
        self._background_task = asyncio.create_task(self._run_data_stream())
        
        logger.info("[AlertMonitor] 监控器已启动")
    
    async def stop(self):
        """停止监控器"""
        logger.info("[AlertMonitor] 正在停止监控器...")
        self._is_running = False
        
        # 停止数据流
        if self.stream:
            await self.stream.stop()
        
        # 取消后台任务
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        
        # 关闭管理器
        if self.state_mgr:
            self.state_mgr.close()
        if self.subscriber_mgr:
            self.subscriber_mgr.close()
        
        logger.info(f"[AlertMonitor] 监控器已停止（处理 {self._tick_count} 个 Tick, "
                   f"触发 {self._alert_count} 次警报）")
    
    async def _run_data_stream(self):
        """运行数据流"""
        try:
            async for tick in self.stream.connect():
                if not self._is_running:
                    break
                
                self._tick_count += 1
                
                # 每 100 个 Tick 打印统计
                if self._tick_count % 100 == 0:
                    logger.info(f"[AlertMonitor] 已处理 {self._tick_count} 个 Tick, "
                               f"警报 {self._alert_count} 次")
        
        except CircuitBreakerException as e:
            # 系统级熔断，发送严重报警
            logger.error(f"[AlertMonitor] [FATAL] 系统熔断：{e}")
            await self._send_system_alert(f"🚨 [系统严重报警] 数据源熔断：{e}")
        
        except Exception as e:
            logger.error(f"[AlertMonitor] 监控循环异常：{e}")
            await self._send_system_alert(f"⚠️ [系统异常] 监控器出错：{e}")
    
    async def _handle_tick(self, tick: TickData):
        """
        处理单个 Tick 数据
        
        Args:
            tick: Tick 数据
        """
        try:
            # 步骤 1: 检查是否休市
            if self.market_cal.is_market_closed():
                return
            
            # 步骤 2: 检查是否处于开盘静默期
            if self.market_cal.is_opening_silent_period():
                return
            
            # 步骤 3: 获取滑窗数据
            window_prices = self.stream.get_window_prices()
            
            # 数据不足，跳过
            if len(window_prices) < 20:
                return
            
            # 步骤 4: 计算 ATR
            atr = calculate_atr_from_ticks(window_prices, period=14)
            
            # 步骤 5: 检测异常波动
            signal = check_abnormal_volatility(
                current_price=tick.price,
                window_prices=window_prices,
                atr_value=atr,
                config=self.config
            )
            
            # 步骤 6: 如果触发，发送预警给所有订阅用户
            if signal.triggered:
                await self._handle_alert(signal, tick)
        
        except Exception as e:
            logger.error(f"[AlertMonitor] 处理 Tick 异常：{e}")
    
    async def _handle_alert(self, signal: Any, tick: TickData):
        """
        处理预警信号并推送给所有订阅用户
        
        Args:
            signal: 波动率信号
            tick: 触发警报的 Tick 数据
        """
        # 检查冷却期
        alert_key = f"price_alert_{signal.signal_type}"
        
        if self.state_mgr.check_cooldown(alert_key):
            # 处于冷却期，跳过
            logger.info(f"[AlertMonitor] 警报 {alert_key} 处于冷却期，跳过")
            return
        
        # 先写状态，后发消息（防漏报设计）
        if not self.state_mgr.set_cooldown(alert_key, self.cooldown_minutes):
            logger.error(f"[AlertMonitor] 设置冷却期失败")
            return
        
        # 构建警报消息
        direction = "📈 上涨" if signal.signal_type == 'up' else "📉 下跌"
        message = (
            f"🚨 {direction} 极速异动！\n\n"
            f"标的：{self.stream.symbol}\n"
            f"当前价格：${signal.current_price:.2f}\n"
            f"变化幅度：{signal.price_change:+.2f} ({signal.price_change_pct:+.2f}%)\n"
            f"触发阈值：${signal.threshold:.2f}\n"
            f"ATR 基准：${signal.atr_value:.2f}\n"
            f"时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"⚠️ 冷却期：{self.cooldown_minutes} 分钟"
        )
        
        # 获取所有订阅用户
        subscribers = self.subscriber_mgr.get_all_subscribers()
        
        if not subscribers:
            logger.info("[AlertMonitor] 无订阅用户，跳过推送")
            self._alert_count += 1
            self._last_alert_time = time.time()
            return
        
        # 推送给所有订阅用户
        for subscriber in subscribers:
            user_id = subscriber['user_id']
            user_name = subscriber.get('user_name', '用户')
            
            if self._send_alert_callback:
                try:
                    await self._send_alert_callback(user_id, message)
                    self.subscriber_mgr.record_alert(user_id)
                    logger.info(f"[AlertMonitor] 已推送警报给 {user_name} ({user_id})")
                except Exception as e:
                    logger.error(f"[AlertMonitor] 推送给 {user_name} 失败：{e}")
                    # 发送失败，压入死信队列
                    self.state_mgr.push_dlq(message, message_type="alert")
        
        self._alert_count += 1
        self._last_alert_time = time.time()
        
        logger.info(f"[AlertMonitor] 警报已发送：{direction} {signal.price_change_pct:.2f}%")
    
    async def _send_system_alert(self, message: str):
        """
        发送系统级报警（给所有订阅用户）
        
        Args:
            message: 系统报警消息
        """
        subscribers = self.subscriber_mgr.get_all_subscribers()
        
        for subscriber in subscribers:
            user_id = subscriber['user_id']
            if self._send_alert_callback:
                try:
                    await self._send_alert_callback(user_id, message)
                except Exception as e:
                    logger.error(f"[AlertMonitor] 系统报警推送失败：{e}")
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取监控器状态
        
        Returns:
            Dict: 状态信息
        """
        subscriber_stats = self.subscriber_mgr.get_stats() if self.subscriber_mgr else {}
        
        return {
            "is_running": self._is_running,
            "tick_count": self._tick_count,
            "alert_count": self._alert_count,
            "last_alert_time": self._last_alert_time,
            "window_size": self.stream.window_size if self.stream else 0,
            "dlq_stats": self.state_mgr.get_dlq_stats() if self.state_mgr else {},
            "subscribers": subscriber_stats
        }


# ==================== 全局实例 ====================

_monitor_instance: Optional[AlertMonitor] = None


def get_monitor() -> Optional[AlertMonitor]:
    """获取监控器实例"""
    return _monitor_instance


def init_monitor(use_mock: bool = False, cooldown_minutes: int = 30) -> AlertMonitor:
    """
    初始化监控器
    
    Args:
        use_mock: 是否使用模拟数据
        cooldown_minutes: 冷却时间
    
    Returns:
        AlertMonitor: 监控器实例
    """
    global _monitor_instance
    _monitor_instance = AlertMonitor(
        use_mock=use_mock,
        cooldown_minutes=cooldown_minutes
    )
    return _monitor_instance


async def start_monitor(send_alert_callback: Callable = None):
    """
    启动监控器
    
    Args:
        send_alert_callback: 发送警报的回调函数 async def callback(user_id: str, message: str)
    """
    if _monitor_instance:
        if send_alert_callback:
            _monitor_instance.set_send_alert_callback(send_alert_callback)
        _monitor_instance.start()


async def stop_monitor():
    """停止监控器"""
    if _monitor_instance:
        await _monitor_instance.stop()


# ==================== 使用示例 ====================

if __name__ == "__main__":
    async def test_send_alert(user_id: str, message: str):
        """测试推送回调"""
        print(f"[推送给 {user_id}] {message}")
    
    async def main():
        # 初始化并启动
        monitor = init_monitor(use_mock=True, cooldown_minutes=5)
        monitor.set_send_alert_callback(test_send_alert)
        monitor.start()
        
        # 运行 30 秒
        await asyncio.sleep(30)
        
        # 查看状态
        print(f"状态：{monitor.get_status()}")
        
        # 停止
        await stop_monitor()
    
    asyncio.run(main())
