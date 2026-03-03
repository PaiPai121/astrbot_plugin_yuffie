#!/usr/bin/env python3
"""
realtime_example.py - 实时数据接入示例

此文件演示如何将 Yuffie 系统接入真实的 WebSocket 数据流，
并在 Web 监控仪表盘中显示实时数据。

【前置要求】
1. 在 config.yaml 中配置有效的 WebSocket 地址
2. 安装 websockets: pip install websockets

【数据源示例】
- 新浪财经：ws://hq.sinajs.cn/ws (需要确认具体地址)
- Binance: wss://stream.binance.com:9443/ws/paxgusdt@trade
- 其他支持 WebSocket 的交易数据源

【运行方式】
1. 配置数据源
2. 运行此脚本作为后台服务
3. Web 仪表盘会自动从 Redis 读取实时数据
"""

import asyncio
import json
import time
from datetime import datetime
from collections import deque

# 核心组件
from core.data_stream import HighFrequencyDataStream, TickData
from core import load_config

# Redis 客户端（用于 Web 仪表盘数据共享）
try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    print("提示：安装 redis 可实现数据共享：pip install redis")

# 配置
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_KEY = "yuffie:latest_prices"
MAX_HISTORY = 1000  # 最多保存 1000 条价格历史


class RealtimeDataCollector:
    """
    实时数据采集器
    
    职责:
        1. 连接 WebSocket 数据流
        2. 解析价格数据
        3. 存储到 Redis（或本地内存）
        4. 供 Web 仪表盘读取
    """
    
    def __init__(self, config: dict = None):
        """
        初始化采集器
        
        Args:
            config: 配置字典
        """
        self.config = config or load_config()
        
        # 价格历史（内存缓存）
        self.price_history: deque = deque(maxlen=MAX_HISTORY)
        
        # Redis 客户端
        self.redis_client = None
        if REDIS_AVAILABLE:
            try:
                self.redis_client = redis.Redis(
                    host=REDIS_HOST,
                    port=REDIS_PORT,
                    decode_responses=True
                )
                self.redis_client.ping()
                print(f"[采集器] Redis 连接成功：{REDIS_HOST}:{REDIS_PORT}")
            except Exception as e:
                print(f"[采集器] Redis 连接失败：{e}")
                self.redis_client = None
        
        # 数据流
        self.stream = None
        
        # 运行状态
        self._is_running = False
        
        print(f"[采集器] 初始化完成，最大历史：{MAX_HISTORY}")
    
    async def start(self):
        """启动数据采集"""
        self._is_running = True
        
        # 创建数据流（使用真实 WebSocket）
        ws_url = self.config.get('data_sources', {}).get(
            'primary_ws',
            'wss://stream.binance.com:9443/ws/paxgusdt@trade'
        )
        
        print(f"[采集器] 正在连接 WebSocket: {ws_url}")
        
        self.stream = HighFrequencyDataStream(
            ws_url=ws_url,
            max_window_size=MAX_HISTORY,
            ssl_verify=True  # 生产环境启用 SSL 验证
        )
        
        # 注册回调
        def on_tick(tick: TickData):
            self._handle_tick(tick)
        
        self.stream.register_callback(on_tick)
        
        # 启动数据流
        try:
            async for tick in self.stream.connect():
                if not self._is_running:
                    break
        except Exception as e:
            print(f"[采集器] 数据流异常：{e}")
        finally:
            await self.stop()
    
    def _handle_tick(self, tick: TickData):
        """
        处理 Tick 数据
        
        Args:
            tick: Tick 数据
        """
        # 添加到历史
        self.price_history.append({
            'timestamp': tick.timestamp,
            'price': tick.price,
            'volume': tick.volume
        })
        
        # 写入 Redis
        if self.redis_client:
            try:
                # 保存最新价格
                latest_data = {
                    'timestamp': tick.timestamp,
                    'price': tick.price,
                    'volume': tick.volume,
                    'symbol': tick.symbol
                }
                self.redis_client.set(
                    f"{REDIS_KEY}:latest",
                    json.dumps(latest_data)
                )
                
                # 保存价格历史（列表）
                price_record = f"{tick.timestamp}:{tick.price}"
                self.redis_client.lpush(REDIS_KEY, price_record)
                self.redis_client.ltrim(REDIS_KEY, 0, MAX_HISTORY - 1)
                
            except Exception as e:
                print(f"[采集器] Redis 写入失败：{e}")
        
        # 打印日志
        now = datetime.fromtimestamp(tick.timestamp).strftime('%H:%M:%S')
        print(f"[{now}] 价格：${tick.price:.2f}")
    
    async def stop(self):
        """停止数据采集"""
        print("[采集器] 正在停止...")
        self._is_running = False
        
        if self.stream:
            await self.stream.stop()
        
        if self.redis_client:
            self.redis_client.close()
        
        print("[采集器] 已停止")
    
    def get_latest_prices(self, count: int = 100) -> list:
        """
        获取最新价格列表
        
        Args:
            count: 获取数量
        
        Returns:
            list: 价格字典列表
        """
        if self.redis_client:
            try:
                records = self.redis_client.lrange(REDIS_KEY, 0, count - 1)
                prices = []
                for record in records:
                    parts = record.split(':')
                    if len(parts) == 2:
                        prices.append({
                            'timestamp': float(parts[0]),
                            'price': float(parts[1])
                        })
                return prices
            except Exception as e:
                print(f"[采集器] Redis 读取失败：{e}")
        
        # 降级到内存
        return list(self.price_history)[-count:]


# ==================== Web 仪表盘数据接口 ====================

def get_realtime_data_for_streamlit() -> dict:
    """
    为 Streamlit 提供实时数据
    
    这是 Web 仪表盘调用的函数
    
    Returns:
        dict: 包含价格历史的字典
    """
    if REDIS_AVAILABLE:
        try:
            client = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                decode_responses=True
            )
            
            # 获取最新价格
            latest_json = client.get(f"{REDIS_KEY}:latest")
            if latest_json:
                latest = json.loads(latest_json)
            else:
                latest = None
            
            # 获取价格历史
            records = client.lrange(REDIS_KEY, 0, 99)
            prices = []
            timestamps = []
            for record in reversed(records):
                parts = record.split(':')
                if len(parts) == 2:
                    timestamps.append(float(parts[0]))
                    prices.append(float(parts[1]))
            
            client.close()
            
            return {
                'latest': latest,
                'prices': prices,
                'timestamps': timestamps,
                'is_realtime': True
            }
            
        except Exception as e:
            print(f"实时数据获取失败：{e}")
    
    # 降级返回空数据
    return {
        'latest': None,
        'prices': [],
        'timestamps': [],
        'is_realtime': False
    }


# ==================== 主程序 ====================

async def main():
    """主函数"""
    print("="*60)
    print("Yuffie 实时数据采集器")
    print("="*60)
    
    config = load_config()
    collector = RealtimeDataCollector(config)
    
    try:
        await collector.start()
    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        await collector.stop()


if __name__ == "__main__":
    asyncio.run(main())
