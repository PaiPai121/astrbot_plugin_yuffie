"""
price_fetcher.py - 金价数据获取模块（东方财富 API 版本）

职责:
    1. 获取国内金价（人民币 CNY/g）- 东方财富 API
    2. 获取国际金价（美元 USD/oz）- Binance REST API
    3. 获取汇率数据（USD/CNY）- 新浪财经
    4. 计算内外盘溢价率
    5. 本地缓存机制（.cache_au9999.json）
    6. 历史数据（.history_au9999.jsonl）

数据源:
    - 国内：东方财富 (118.Au9999) - 上海黄金交易所现货
    - 国际：Binance REST API (PAXGUSDT)
    - 汇率：新浪财经 (usdcny)
"""

import os
import json
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

# 异步 HTTP 客户端
try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    print("[PriceFetcher] 警告：aiohttp 未安装，请运行：pip install aiohttp")

# 同步 HTTP 客户端（用于东方财富 API）
try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    print("[PriceFetcher] 警告：requests 未安装，请运行：pip install requests")

# 获取项目根目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
CACHE_FILE = os.path.join(PROJECT_ROOT, ".cache_au9999.json")
HISTORY_FILE = os.path.join(PROJECT_ROOT, ".history_au9999.jsonl")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.yaml")


def load_config() -> dict:
    """加载配置文件"""
    default_config = {
        "data_sources": {
            "domestic_gold_api": "http://push2.eastmoney.com/api/qt/stock/get?secid=118.Au9999&fields=f43,f60",
            "exchange_rate_api": "http://hq.sinajs.cn/list=usdcny"
        }
    }
    
    try:
        import yaml
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config:
                return config
    except Exception as e:
        print(f"[PriceFetcher] 加载配置文件失败：{e}")
    
    return default_config


# ==================== 缓存管理 ====================

def _read_cache() -> Optional[Dict[str, Any]]:
    """读取本地缓存"""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"[PriceFetcher] 读取缓存：¥{data.get('price', 0):.2f}/克 @ {data.get('timestamp', 'N/A')}")
                return data
    except Exception as e:
        print(f"[PriceFetcher] 读取缓存失败：{e}")
    
    return None


def _write_cache(price: float, is_live: bool) -> bool:
    """写入本地缓存"""
    try:
        data = {
            "price": price,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_live": is_live
        }
        
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"[PriceFetcher] 写入缓存：¥{price:.2f}/克 (is_live={is_live})")
        return True
    except Exception as e:
        print(f"[PriceFetcher] 写入缓存失败：{e}")
        return False


def _read_history(max_points: int = 100) -> List[Dict[str, Any]]:
    """读取历史价格数据（JSONL 格式，只读最后 N 行）"""
    try:
        if os.path.exists(HISTORY_FILE):
            history = []
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                for line in lines[-max_points:]:
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        history.append(data)
            return history
    except Exception as e:
        print(f"[PriceFetcher] 读取历史数据失败：{e}")
    
    return []


def _write_history(price: float, timestamp: str) -> bool:
    """追加写入历史价格数据（JSONL 格式，追加模式）"""
    try:
        new_point = {
            "price": price,
            "timestamp": timestamp
        }
        
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps(new_point, ensure_ascii=False) + '\n')
        
        return True
    except Exception as e:
        print(f"[PriceFetcher] 写入历史数据失败：{e}")
        return False


# ==================== 交易时间判定 ====================

def _is_trading_time() -> Tuple[bool, str]:
    """检查当前是否在交易时间内"""
    now = datetime.now()
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    current_time = hour * 60 + minute
    
    if weekday >= 5:
        return False, "周末休市"
    
    if 540 <= current_time <= 690:
        return True, "早盘"
    elif 810 <= current_time <= 930:
        return True, "午盘"
    elif current_time >= 1200 or current_time <= 150:
        return True, "夜盘"
    
    return False, "非交易时间"


# ==================== 国内金价获取（东方财富 API） ====================

async def fetch_domestic_gold_price(timeout: float = 10.0) -> Dict[str, Any]:
    """
    获取国内金价（人民币 CNY/g）- 东方财富 API + 异步包装
    """
    if not REQUESTS_AVAILABLE:
        print("[PriceFetcher] requests 库不可用")
        cache = _read_cache()
        if cache:
            return {
                "price": cache.get("price", 0),
                "is_live": False,
                "timestamp": cache.get("timestamp", ""),
                "source": "本地缓存 (requests 不可用)"
            }
        return {"price": 0, "is_live": False, "timestamp": "", "source": "不可用"}

    eastmoney_url = 'http://push2.eastmoney.com/api/qt/stock/get?secid=118.Au9999&fields=f43,f60'
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    def _fetch_price():
        """同步请求函数（在后台线程执行）"""
        try:
            resp = requests.get(
                eastmoney_url, 
                headers=headers, 
                timeout=timeout,
                proxies={"http": None, "https": None}
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"[PriceFetcher] 东方财富 API 请求失败：{e}")
            return None

    json_data = await asyncio.to_thread(_fetch_price)

    price = None
    api_success = False

    if json_data:
        data = json_data.get("data", {})
        if data:
            latest = data.get("f43")
            if latest is not None and latest != "-" and latest != "":
                try:
                    price = float(latest) / 100.0
                    if 100 < price < 10000:
                        api_success = True
                        print(f"[PriceFetcher] 东方财富 API - 国内金价：¥{price:.2f}/克")
                except (ValueError, TypeError):
                    pass
            
            if not api_success:
                prev_close = data.get("f60")
                if prev_close is not None and prev_close != "-" and prev_close != "":
                    try:
                        price = float(prev_close) / 100.0
                        if 100 < price < 10000:
                            api_success = True
                            print(f"[PriceFetcher] 东方财富 API - 国内金价 (昨收): ¥{price:.2f}/克")
                    except (ValueError, TypeError):
                        pass

    is_trading, period_desc = _is_trading_time()
    
    if api_success and price:
        is_live = is_trading
        _write_cache(price, is_live)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _write_history(price, timestamp)
        source = f"东方财富 ({period_desc})"
        
        return {
            "price": price,
            "is_live": is_live,
            "timestamp": timestamp,
            "source": source
        }
    
    print("[PriceFetcher] 东方财富 API 失败，读取本地缓存")
    cache = _read_cache()
    
    if cache:
        return {
            "price": cache.get("price", 0),
            "is_live": False,
            "timestamp": cache.get("timestamp", ""),
            "source": "本地缓存 (API 失败)"
        }
    
    return {
        "price": 0,
        "is_live": False,
        "timestamp": "",
        "source": "不可用 (无缓存)"
    }


# ==================== 国际金价获取 ====================

async def fetch_international_gold_price(timeout: float = 10.0) -> Optional[float]:
    """获取国际金价（美元 USD/oz）- Binance REST API"""
    if not AIOHTTP_AVAILABLE:
        return None

    binance_url = 'https://api.binance.com/api/v3/ticker/price?symbol=PAXGUSDT'
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(binance_url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                data = await response.json()
                price = float(data.get('price', 0))
                
                if price > 0:
                    print(f"[PriceFetcher] Binance API - 国际金价：${price:.2f}/oz")
                    return price
        except Exception as e:
            print(f"[PriceFetcher] Binance API 失败：{e}")
    
    return None


# ==================== 汇率获取 ====================

async def fetch_usd_cny_rate(timeout: float = 10.0) -> Optional[float]:
    """获取美元兑人民币汇率 - 新浪财经"""
    if not AIOHTTP_AVAILABLE:
        return None

    sina_url = 'http://hq.sinajs.cn/list=usdcny'
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Referer': 'https://finance.sina.com.cn/'
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(sina_url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                content = await response.text(encoding='gbk')
                
                if 'hq_str_usdcny' in content:
                    start = content.find('"') + 1
                    end = content.rfind('"')
                    if start > 0 and end > start:
                        data_str = content[start:end]
                        parts = data_str.split(',')
                        
                        if len(parts) >= 2 and parts[1]:
                            try:
                                rate = float(parts[1])
                                if rate > 0:
                                    print(f"[PriceFetcher] 汇率 (USD/CNY): {rate:.4f}")
                                    return rate
                            except ValueError:
                                pass
        except Exception as e:
            print(f"[PriceFetcher] 汇率获取失败：{e}")
    
    return None


# ==================== 综合数据获取 ====================

async def get_all_gold_prices() -> Dict[str, Any]:
    """异步获取所有金价相关数据"""
    result = {
        'domestic_price_cny_g': None,
        'international_price_usd_oz': None,
        'exchange_rate': None,
        'premium_rate': None,
        'domestic_is_live': False,
        'domestic_timestamp': '',
        'domestic_source': '',
        'timestamp': time.time()
    }
    
    domestic_task = fetch_domestic_gold_price()
    intl_task = fetch_international_gold_price()
    rate_task = fetch_usd_cny_rate()
    
    try:
        domestic_data, intl_price, exchange_rate = await asyncio.gather(
            domestic_task, intl_task, rate_task,
            return_exceptions=True
        )
    except Exception as e:
        print(f"[PriceFetcher] 并行获取失败：{e}")
        return result
    
    if isinstance(domestic_data, Exception):
        domestic_data = {"price": 0, "is_live": False, "timestamp": "", "source": "异常"}
    if isinstance(intl_price, Exception):
        intl_price = None
    if isinstance(exchange_rate, Exception):
        exchange_rate = None
    
    result['domestic_price_cny_g'] = domestic_data.get('price')
    result['domestic_is_live'] = domestic_data.get('is_live', False)
    result['domestic_timestamp'] = domestic_data.get('timestamp', '')
    result['domestic_source'] = domestic_data.get('source', '')
    result['international_price_usd_oz'] = intl_price
    result['exchange_rate'] = exchange_rate
    
    if result['domestic_price_cny_g'] and intl_price and exchange_rate:
        result['premium_rate'] = calculate_premium_rate(
            result['domestic_price_cny_g'], intl_price, exchange_rate
        )
    
    return result


def get_domestic_gold_history(max_points: int = 100) -> List[Dict[str, Any]]:
    """获取国内金价历史数据"""
    return _read_history(max_points)


# ==================== 历史 K 线数据获取 ====================

async def fetch_intl_gold_klines(interval: str = "1d", limit: int = 60) -> List[Dict[str, Any]]:
    """获取国际金价 K 线数据（Binance REST API）"""
    if not AIOHTTP_AVAILABLE:
        return []
    
    binance_url = 'https://api.binance.com/api/v3/klines'
    params = {
        'symbol': 'PAXGUSDT',
        'interval': interval,
        'limit': min(limit, 1000)
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(binance_url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                data = await response.json()
                
                klines = []
                for k in data:
                    klines.append({
                        "timestamp": datetime.fromtimestamp(k[0] / 1000),
                        "open": float(k[1]),
                        "high": float(k[2]),
                        "low": float(k[3]),
                        "close": float(k[4])
                    })
                
                print(f"[PriceFetcher] 国际金价 K 线：获取 {len(klines)} 条 ({interval})")
                return klines
                
    except Exception as e:
        print(f"[PriceFetcher] 国际金价 K 线失败：{e}")
    
    return []


async def fetch_domestic_gold_klines(interval: str = "1d", limit: int = 60) -> List[Dict[str, Any]]:
    """获取国内金价 K 线数据 - 免费接口不支持，直接返回空列表"""
    print(f"[PriceFetcher] 国内金价 K 线：免费接口不支持历史数据")
    return []


# ==================== 溢价率计算 ====================

def calculate_premium_rate(
    domestic_price_cny_g: float,
    international_price_usd_oz: float,
    exchange_rate: float
) -> float:
    """计算内外盘溢价率"""
    OUNCE_TO_GRAM = 31.1034768
    
    domestic_cny_oz = domestic_price_cny_g * OUNCE_TO_GRAM
    intl_cny_oz = international_price_usd_oz * exchange_rate
    
    if intl_cny_oz == 0:
        return 0.0
    
    premium_rate = (domestic_cny_oz - intl_cny_oz) / intl_cny_oz * 100
    return premium_rate


# ==================== 使用示例 ====================

if __name__ == "__main__":
    async def main():
        print("="*60)
        print("国内金价获取测试（东方财富 API）")
        print("="*60)
        
        print("\n[测试] 获取国内金价...")
        try:
            domestic_data = await fetch_domestic_gold_price()
            print(f"价格：¥{domestic_data['price']:.2f}/克")
            print(f"实时：{domestic_data['is_live']}")
            print(f"时间：{domestic_data['timestamp']}")
            print(f"来源：{domestic_data['source']}")
        except Exception as e:
            print(f"✗ 国内金价获取异常：{e}")
        
        print("\n[测试] 获取综合数据...")
        try:
            data = await get_all_gold_prices()
            print(f"国内金价：¥{data['domestic_price_cny_g']}/克")
            print(f"实时标志：{data['domestic_is_live']}")
            print(f"国际金价：${data['international_price_usd_oz']}/oz")
            print(f"汇率：{data['exchange_rate']}")
            if data['premium_rate']:
                print(f"溢价率：{data['premium_rate']:+.2f}%")
        except Exception as e:
            print(f"✗ 综合数据获取异常：{e}")

    asyncio.run(main())
