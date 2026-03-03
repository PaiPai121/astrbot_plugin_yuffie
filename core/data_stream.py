"""
data_stream.py - 高频数据流引擎

职责:
    1. 使用 WebSocket 长连接接收实时价格数据流
    2. 维护内存滑窗（Sliding Window）存储最近的价格 Tick 数据
    3. 实现断线自动重连（指数退避策略）
    4. 重连失败超过 3 次后抛出系统级熔断异常

设计原则:
    - 高可用：断线自动重连，指数退避避免频繁重试
    - 低延迟：内存滑窗提供微秒级数据访问
    - 熔断保护：重连失败后抛出异常，绝不静默降级到延迟数据源
    - 可扩展：预留消息解析方法，方便适配不同数据源
"""

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import (
    Optional,
    Callable,
    AsyncGenerator,
    List,
    Dict,
    Any,
    Union
)
import os

# 尝试导入 websockets 库
try:
    import websockets
    from websockets.exceptions import ConnectionClosed, WebSocketException
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
    print("[DataStream] 警告：websockets 未安装，将使用模拟模式")
    print("[DataStream] 请运行：pip install websockets")

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


# ==================== 数据模型 ====================

@dataclass
class TickData:
    """
    Tick 数据模型 - 存储单个价格快照
    
    Attributes:
        timestamp: 时间戳（Unix 时间，秒）
        price: 价格
        volume: 成交量（可选）
        symbol: 交易对符号
        raw_data: 原始数据（用于调试）
    """
    timestamp: float
    price: float
    volume: float = 0.0
    symbol: str = ""
    raw_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "timestamp": self.timestamp,
            "price": self.price,
            "volume": self.volume,
            "symbol": self.symbol
        }
    
    @property
    def datetime(self) -> datetime:
        """获取 datetime 对象"""
        return datetime.fromtimestamp(self.timestamp)


@dataclass
class StreamEvent:
    """
    数据流事件 - 封装 WebSocket 事件
    
    Attributes:
        event_type: 事件类型（tick, error, reconnect, circuit_breaker）
        data: 事件数据
        message: 事件消息
    """
    event_type: str
    data: Optional[Any] = None
    message: str = ""


# ==================== 自定义异常 ====================

class CircuitBreakerException(Exception):
    """
    系统级熔断异常
    
    当 WebSocket 重连超过最大次数后抛出此异常，
    表示数据源已不可用，系统应停止监控并报警
    """
    def __init__(self, message: str, reconnect_attempts: int = 0):
        super().__init__(message)
        self.reconnect_attempts = reconnect_attempts
        self.timestamp = time.time()


class DataStreamError(Exception):
    """数据流通用异常"""
    pass


# ==================== 配置加载 ====================

def load_config() -> dict:
    """
    加载配置文件 config.yaml
    
    Returns:
        dict: 配置字典
    """
    default_config = {
        "data_sources": {
            "primary_ws": "wss://hq.sinajs.cn/ws",
            "fallback_api": "yfinance"
        },
        "monitor": {
            "symbol": "GC=F"
        }
    }
    
    try:
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config:
                return config
    except Exception as e:
        print(f"[DataStream] 加载配置文件失败：{e}，使用默认配置")
    
    return default_config


# ==================== 高频数据流引擎 ====================

class HighFrequencyDataStream:
    """
    高频数据流引擎
    
    核心功能:
        1. WebSocket 长连接管理
        2. 内存滑窗（deque）维护最近 N 秒的价格数据
        3. 断线自动重连（指数退避）
        4. 熔断保护（重连失败 > 3 次抛出异常）
        5. 异步生成器供外部消费数据
    
    使用示例:
        async def main():
            stream = HighFrequencyDataStream()
            async for tick in stream.connect():
                print(f"收到价格：{tick.price}")
    """
    
    # 默认配置
    DEFAULT_MAX_WINDOW_SIZE = 300  # 滑窗最大容量（300 个 Tick）
    DEFAULT_MAX_RECONNECT_ATTEMPTS = 3  # 最大重连次数
    DEFAULT_BASE_BACKOFF = 1.0  # 基础退避时间（秒）
    DEFAULT_MAX_BACKOFF = 30.0  # 最大退避时间（秒）
    
    def __init__(
        self,
        ws_url: Optional[str] = None,
        symbol: Optional[str] = None,
        max_window_size: int = DEFAULT_MAX_WINDOW_SIZE,
        max_reconnect_attempts: int = DEFAULT_MAX_RECONNECT_ATTEMPTS,
        config_path: Optional[str] = None,
        ssl_verify: bool = True  # 是否验证 SSL 证书
    ):
        """
        初始化高频数据流
        
        Args:
            ws_url: WebSocket URL，如果为 None 则从 config.yaml 读取
            symbol: 交易对符号（如 "GC=F" 或 "XAUUSD"）
            max_window_size: 滑窗最大容量（Tick 数量）
            max_reconnect_attempts: 最大重连次数（超过则熔断）
            config_path: 配置文件路径
        """
        # 加载配置
        config = load_config() if config_path is None else self._load_config_from_path(config_path)
        
        # WebSocket URL
        self.ws_url = ws_url or config.get("data_sources", {}).get(
            "primary_ws", "wss://hq.sinajs.cn/ws"
        )
        
        # 交易对符号
        self.symbol = symbol or config.get("monitor", {}).get("symbol", "GC=F")
        
        # 滑窗配置
        self.max_window_size = max_window_size
        self._window: deque = deque(maxlen=max_window_size)
        
        # 重连配置
        self.max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_attempts = 0
        self._base_backoff = self.DEFAULT_BASE_BACKOFF
        self._max_backoff = self.DEFAULT_MAX_BACKOFF

        # SSL 配置
        self.ssl_verify = ssl_verify
        
        # 连接状态
        self._websocket = None
        self._is_connected = False
        self._is_running = False
        self._last_message_time = 0.0
        
        # 回调函数列表
        self._callbacks: List[Callable[[TickData], None]] = []
        
        # 事件队列（用于异步生成器）
        self._event_queue: asyncio.Queue = asyncio.Queue()
        
        # 锁（线程安全）
        self._lock = asyncio.Lock()
        
        print(f"[DataStream] 初始化完成：URL={self.ws_url}, Symbol={self.symbol}, "
              f"Window={max_window_size}")
    
    def _load_config_from_path(self, config_path: str) -> dict:
        """从指定路径加载配置"""
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[DataStream] 加载配置文件失败：{e}")
            return {}
    
    def register_callback(self, callback: Callable[[TickData], None]):
        """
        注册回调函数
        
        当收到新的 Tick 数据时，会调用所有注册的回调函数
        
        Args:
            callback: 回调函数，接收 TickData 参数
        """
        self._callbacks.append(callback)
        print(f"[DataStream] 已注册回调函数：{callback.__name__}")
    
    def unregister_callback(self, callback: Callable[[TickData], None]):
        """注销回调函数"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)
    
    def _parse_message(self, msg: str) -> Optional[TickData]:
        """
        解析 WebSocket 消息

        根据数据源的不同格式解析 JSON 消息，提取价格和成交量

        支持的数据源格式:
            1. 新浪财经：{"symbol": "GC=F", "price": 2650.50, "time": "2026-03-01 10:30:00"}
            2. Binance PAXG/USDT: {"p": "2650.50", "T": 1709280600000, "v": "100.5"}
            3. 通用格式：{"price": 2650.50, "timestamp": 1709280600}

        Args:
            msg: WebSocket 原始消息（JSON 字符串或纯文本）

        Returns:
            TickData: 解析后的 Tick 数据，如果解析失败返回 None

        注意:
            此方法设计为可扩展的，用户可根据实际数据源修改解析逻辑
            非 JSON 消息（如 ping/pong 纯文本）会返回 None，不会抛出异常
        """
        # 快速检查：如果不是 JSON 对象/数组开头，直接返回 None
        msg_stripped = msg.strip()
        if not (msg_stripped.startswith('{') or msg_stripped.startswith('[')):
            # 可能是 ping/pong 或其他系统消息
            print(f"[DataStream] [WARNING] 收到非 JSON 消息：{msg[:100]}")
            return None

        try:
            data = json.loads(msg)

            # 尝试多种格式解析
            price = None
            timestamp = None
            volume = 0.0

            # === 格式 1: Binance 格式 ===
            # {"p": "2650.50", "T": 1709280600000, "v": "100.5"}
            if "p" in data:
                price = float(data["p"])
                # Binance 时间戳是毫秒
                timestamp = data.get("T", time.time() * 1000) / 1000.0
                volume = float(data.get("v", 0))

            # === 格式 2: 新浪财经格式 ===
            # {"symbol": "GC=F", "price": 2650.50, "time": "2026-03-01 10:30:00"}
            elif "price" in data and isinstance(data["price"], (int, float)):
                price = float(data["price"])

                # 尝试解析时间字符串
                if "time" in data:
                    try:
                        dt = datetime.strptime(data["time"], "%Y-%m-%d %H:%M:%S")
                        timestamp = dt.timestamp()
                    except ValueError:
                        timestamp = time.time()
                else:
                    timestamp = time.time()

                volume = float(data.get("volume", 0))

            # === 格式 3: 通用格式 ===
            # {"price": 2650.50, "timestamp": 1709280600}
            elif "price" in data:
                price = float(data["price"])
                timestamp = float(data.get("timestamp", time.time()))
                volume = float(data.get("volume", 0))

            # === 格式 4: 数组格式（某些 WS 返回数组）===
            # [symbol, price, timestamp, volume]
            elif isinstance(data, list) and len(data) >= 2:
                price = float(data[1])
                timestamp = float(data[2]) if len(data) > 2 else time.time()
                volume = float(data[3]) if len(data) > 3 else 0.0

            # 验证价格有效性
            if price is None or price <= 0:
                # 不是价格数据，可能是其他类型的消息
                print(f"[DataStream] [WARNING] 无有效价格数据：{data}")
                return None

            if timestamp is None:
                timestamp = time.time()

            # 创建 TickData
            tick = TickData(
                timestamp=timestamp,
                price=price,
                volume=volume,
                symbol=self.symbol,
                raw_data=data
            )

            return tick

        except json.JSONDecodeError as e:
            # JSON 解析失败，可能是纯文本消息
            print(f"[DataStream] [WARNING] JSON 解析失败：{e}, 消息：{msg[:100]}")
            return None
        except (KeyError, ValueError, TypeError) as e:
            print(f"[DataStream] [WARNING] 数据解析失败：{e}, 数据：{msg[:100]}")
            return None
        except Exception as e:
            print(f"[DataStream] [WARNING] 未知解析错误：{e}")
            return None
    
    async def _calculate_backoff(self) -> float:
        """
        计算指数退避时间
        
        公式：backoff = min(base * 2^(attempt-1), max_backoff)
        
        Returns:
            float: 退避时间（秒）
        """
        backoff = min(
            self._base_backoff * (2 ** (self._reconnect_attempts - 1)),
            self._max_backoff
        )
        # 添加少量随机抖动（0-1 秒），避免多个客户端同时重连
        import random
        jitter = random.uniform(0, 1)
        return backoff + jitter
    
    async def _connect_websocket(self) -> bool:
        """
        建立 WebSocket 连接

        Returns:
            bool: 连接是否成功
        """
        if not WEBSOCKETS_AVAILABLE:
            print("[DataStream] websockets 库不可用，使用模拟模式")
            return False

        try:
            print(f"[DataStream] 正在连接 WebSocket: {self.ws_url}")

            # 设置连接参数
            connect_kwargs = {
                "ping_interval": 30,  # 每 30 秒发送 ping
                "ping_timeout": 10,   # 10 秒超时
                "close_timeout": 5,   # 5 秒关闭超时
                "max_size": 10**6,    # 最大消息 1MB
            }

            # SSL 配置
            if not self.ssl_verify:
                # 不验证 SSL 证书（用于测试或自签名证书）
                import ssl
                ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                connect_kwargs["ssl"] = ssl_context
            elif self.ws_url.startswith("wss://"):
                # 使用系统默认证书验证
                connect_kwargs["ssl"] = True

            self._websocket = await websockets.connect(
                self.ws_url,
                **connect_kwargs
            )

            self._is_connected = True
            self._reconnect_attempts = 0  # 重置重连计数
            print(f"[DataStream] WebSocket 连接成功")
            return True

        except WebSocketException as e:
            print(f"[DataStream] WebSocket 连接失败：{e}")
            self._is_connected = False
            return False
        except Exception as e:
            print(f"[DataStream] 连接异常：{e}")
            self._is_connected = False
            return False
    
    async def _reconnect(self) -> bool:
        """
        执行重连逻辑（指数退避）
        
        Returns:
            bool: 重连是否成功
        
        Raises:
            CircuitBreakerException: 重连次数超过上限时抛出熔断异常
        """
        self._reconnect_attempts += 1
        
        if self._reconnect_attempts > self.max_reconnect_attempts:
            msg = (f"WebSocket 重连失败超过 {self.max_reconnect_attempts} 次，"
                   f"触发系统级熔断")
            print(f"[DataStream] [FATAL] {msg}")
            raise CircuitBreakerException(msg, self._reconnect_attempts)
        
        # 计算退避时间
        backoff = await self._calculate_backoff()
        print(f"[DataStream] {self._reconnect_attempts}/{self.max_reconnect_attempts} "
              f"重连，等待 {backoff:.2f} 秒...")
        
        await asyncio.sleep(backoff)
        
        return await self._connect_websocket()
    
    async def _handle_message(self, msg: str):
        """
        处理接收到的 WebSocket 消息
        
        Args:
            msg: 原始消息字符串
        """
        self._last_message_time = time.time()
        
        # 解析消息
        tick = self._parse_message(msg)
        
        if tick is None:
            return
        
        # 更新滑窗
        async with self._lock:
            self._window.append(tick)
        
        # 调用回调函数
        for callback in self._callbacks:
            try:
                # 同步回调
                callback(tick)
            except Exception as e:
                print(f"[DataStream] 回调函数执行失败 {callback.__name__}: {e}")
        
        # 放入事件队列（供异步生成器消费）
        await self._event_queue.put(StreamEvent(
            event_type="tick",
            data=tick
        ))
    
    async def _receive_loop(self):
        """
        WebSocket 接收循环
        
        持续从 WebSocket 接收消息并处理
        """
        while self._is_running and self._is_connected:
            try:
                if self._websocket is None:
                    await asyncio.sleep(0.1)
                    continue
                
                msg = await self._websocket.recv()
                await self._handle_message(msg)
                
            except ConnectionClosed as e:
                print(f"[DataStream] 连接关闭：code={e.code}, reason={e.reason}")
                self._is_connected = False
                break
            except WebSocketException as e:
                print(f"[DataStream] WebSocket 异常：{e}")
                self._is_connected = False
                break
            except Exception as e:
                print(f"[DataStream] 接收消息异常：{e}")
                # 继续循环，不中断
    
    async def _run_with_reconnect(self):
        """
        主运行循环（包含重连逻辑）
        
        此方法会持续运行，直到被外部停止或触发熔断
        """
        self._is_running = True
        
        while self._is_running:
            try:
                # 尝试连接
                if not self._is_connected:
                    if not await self._connect_websocket():
                        # 首次连接失败，尝试重连
                        try:
                            if not await self._reconnect():
                                continue
                        except CircuitBreakerException:
                            # 熔断异常，停止运行
                            await self._event_queue.put(StreamEvent(
                                event_type="circuit_breaker",
                                message=f"重连失败 {self._reconnect_attempts} 次，系统熔断"
                            ))
                            break
                    else:
                        # 连接成功，放入队列
                        await self._event_queue.put(StreamEvent(
                            event_type="reconnect",
                            message="WebSocket 连接成功"
                        ))
                
                # 接收消息循环
                await self._receive_loop()
                
            except CircuitBreakerException as e:
                print(f"[DataStream] 熔断异常：{e}")
                await self._event_queue.put(StreamEvent(
                    event_type="circuit_breaker",
                    message=str(e)
                ))
                break
            except asyncio.CancelledError:
                print("[DataStream] 任务被取消")
                break
            except Exception as e:
                print(f"[DataStream] 主循环异常：{e}")
                self._is_connected = False
                # 等待后重试
                try:
                    await self._reconnect()
                except CircuitBreakerException:
                    break
    
    async def connect(self) -> AsyncGenerator[TickData, None]:
        """
        连接 WebSocket 并返回异步生成器

        使用方式:
            async for tick in stream.connect():
                print(f"价格：{tick.price}")

        Yields:
            TickData: 实时 Tick 数据

        Raises:
            CircuitBreakerException: 当重连失败超过最大次数时抛出
        """
        # 启动后台任务
        self._is_running = True  # 确保运行标志为 True
        task = asyncio.create_task(self._run_with_reconnect())

        try:
            while self._is_running:
                # 从队列中获取事件
                event = await self._event_queue.get()

                if event.event_type == "circuit_breaker":
                    print(f"[DataStream] 熔断触发，停止数据流")
                    self._is_running = False
                    # 重新抛出熔断异常
                    raise CircuitBreakerException(
                        event.message,
                        self._reconnect_attempts
                    )

                if event.event_type == "tick" and event.data:
                    yield event.data

        except asyncio.CancelledError:
            print("[DataStream] 生成器被取消")
        except GeneratorExit:
            pass
        finally:
            # 清理
            self._is_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    async def start(self):
        """
        启动数据流（后台模式）
        
        此方法会启动后台任务，但不会阻塞当前协程
        需要配合回调函数使用
        """
        task = asyncio.create_task(self._run_with_reconnect())
        self._background_task = task
        print("[DataStream] 数据流已启动（后台模式）")
        return task
    
    async def stop(self):
        """停止数据流"""
        print("[DataStream] 正在停止数据流...")
        self._is_running = False
        self._is_connected = False
        
        # 关闭 WebSocket
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
        
        # 取消后台任务
        if hasattr(self, '_background_task'):
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
        
        print("[DataStream] 数据流已停止")
    
    # ==================== 滑窗数据访问 ====================
    
    def get_latest_tick(self) -> Optional[TickData]:
        """
        获取最新的 Tick 数据
        
        Returns:
            TickData: 最新 Tick，如果滑窗为空返回 None
        """
        if self._window:
            return self._window[-1]
        return None
    
    def get_latest_price(self) -> Optional[float]:
        """
        获取最新价格
        
        Returns:
            float: 最新价格，如果滑窗为空返回 None
        """
        tick = self.get_latest_tick()
        return tick.price if tick else None
    
    def get_window(self, size: Optional[int] = None) -> List[TickData]:
        """
        获取滑窗数据

        Args:
            size: 获取数量，如果为 None 则返回全部

        Returns:
            List[TickData]: 滑窗数据列表（按时间正序）
        """
        # 直接返回（滑窗操作是线程安全的，因为 deque 的 append 和 list 转换是原子的）
        if size is None:
            return list(self._window)
        else:
            window_list = list(self._window)
            return window_list[-size:] if len(window_list) >= size else window_list
    
    def get_window_prices(self, size: Optional[int] = None) -> List[float]:
        """
        获取滑窗价格列表
        
        Args:
            size: 获取数量
        
        Returns:
            List[float]: 价格列表
        """
        window = self.get_window(size)
        return [tick.price for tick in window]
    
    def get_window_stats(self) -> Dict[str, Any]:
        """
        获取滑窗统计信息
        
        Returns:
            Dict: 包含 count, min, max, avg, std 等统计
        """
        prices = self.get_window_prices()
        
        if not prices:
            return {
                "count": 0,
                "min": None,
                "max": None,
                "avg": None,
                "std": None
            }
        
        import statistics
        
        return {
            "count": len(prices),
            "min": min(prices),
            "max": max(prices),
            "avg": statistics.mean(prices),
            "std": statistics.stdev(prices) if len(prices) > 1 else 0.0
        }
    
    @property
    def is_connected(self) -> bool:
        """连接状态"""
        return self._is_connected
    
    @property
    def window_size(self) -> int:
        """当前滑窗大小"""
        return len(self._window)
    
    @property
    def reconnect_attempts(self) -> int:
        """当前重连次数"""
        return self._reconnect_attempts


# ==================== 模拟数据流（用于测试） ====================

class MockDataStream(HighFrequencyDataStream):
    """
    模拟数据流 - 用于测试和开发
    
    当 websockets 库不可用或需要离线测试时使用
    生成随机价格波动数据
    """
    
    def __init__(self, base_price: float = 2650.0, volatility: float = 0.001, **kwargs):
        """
        初始化模拟数据流
        
        Args:
            base_price: 基础价格
            volatility: 波动率（标准差）
            **kwargs: 传递给父类的参数
        """
        super().__init__(**kwargs)
        self.base_price = base_price
        self.volatility = volatility
        self._current_price = base_price
    
    async def _generate_mock_tick(self) -> TickData:
        """生成模拟 Tick 数据"""
        import random
        
        # 随机游走价格
        change = random.gauss(0, self.base_price * self.volatility)
        self._current_price += change
        self._current_price = max(self._current_price, self.base_price * 0.9)  # 下限
        
        tick = TickData(
            timestamp=time.time(),
            price=round(self._current_price, 2),
            volume=round(random.uniform(10, 1000), 2),
            symbol=self.symbol
        )
        
        return tick
    
    async def _run_mock(self):
        """模拟运行循环"""
        self._is_running = True
        
        while self._is_running:
            tick = await self._generate_mock_tick()
            
            # 更新滑窗
            async with self._lock:
                self._window.append(tick)
            
            # 调用回调
            for callback in self._callbacks:
                try:
                    callback(tick)
                except Exception as e:
                    print(f"[MockDataStream] 回调失败：{e}")
            
            # 放入队列
            await self._event_queue.put(StreamEvent(
                event_type="tick",
                data=tick
            ))
            
            # 模拟 1 秒间隔
            await asyncio.sleep(1)
    
    async def connect(self) -> AsyncGenerator[TickData, None]:
        """覆盖父类方法，使用模拟数据"""
        self._is_running = True  # 确保运行标志为 True
        task = asyncio.create_task(self._run_mock())

        try:
            while self._is_running:
                event = await self._event_queue.get()
                if event.event_type == "tick" and event.data:
                    yield event.data
        except GeneratorExit:
            pass
        finally:
            self._is_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


# ==================== 工厂函数 ====================

def create_data_stream(
    use_mock: bool = False,
    **kwargs
) -> Union[HighFrequencyDataStream, MockDataStream]:
    """
    创建数据流实例的工厂函数
    
    Args:
        use_mock: 是否使用模拟模式
        **kwargs: 传递给数据流的参数
    
    Returns:
        HighFrequencyDataStream 或 MockDataStream
    """
    if use_mock or not WEBSOCKETS_AVAILABLE:
        print("[DataStream] 使用模拟数据流")
        return MockDataStream(**kwargs)
    else:
        print("[DataStream] 使用真实 WebSocket 数据流")
        return HighFrequencyDataStream(**kwargs)


# ==================== 使用示例 ====================

async def example_usage():
    """使用示例"""
    print("=== HighFrequencyDataStream 使用示例 ===\n")
    
    # 创建数据流（使用模拟模式）
    stream = create_data_stream(use_mock=True, base_price=2650.0)
    
    # 注册回调
    def on_tick(tick: TickData):
        print(f"[回调] 价格更新：{tick.price} @ {tick.datetime.strftime('%H:%M:%S')}")
    
    stream.register_callback(on_tick)
    
    # 使用异步生成器消费
    print("开始接收数据流（5 秒后停止）...\n")
    
    try:
        async for tick in stream.connect():
            print(f"收到 Tick: 价格={tick.price}, 滑窗大小={stream.window_size}")
            
            # 5 秒后停止
            if time.time() - tick.timestamp > 5:
                break
    except CircuitBreakerException as e:
        print(f"熔断触发：{e}")
    finally:
        await stream.stop()
    
    # 获取滑窗统计
    stats = stream.get_window_stats()
    print(f"\n滑窗统计：{stats}")


if __name__ == "__main__":
    asyncio.run(example_usage())
