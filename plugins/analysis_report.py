"""
analysis_report.py - 深度分析插件（异步版本，包含国内金价）

职责:
    1. 响应用户指令（如 /黄金分析）
    2. 获取当前盘面数据（包含国内金价、汇率、溢价率）
    3. 组装成 Markdown 研报回复

新增板块:
    - 国内 Au99.99 现货金价（人民币/克）
    - 当前 USD/CNY 汇率
    - 内外盘溢价率（正数为国内溢价，负数为国内折价）
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, Any, List

# AstrBot 导入
try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.message_components import Plain, Image
except ImportError:
    import logging
    logger = logging.getLogger("Yuffie")
    
    class AstrMessageEvent:
        pass

# 核心组件导入
from core.data_stream import create_data_stream, TickData
from core.market_cal import MarketCalendar
from core.indicators import (
    calculate_atr_from_ticks,
    calculate_rsi,
    calculate_ma,
    calculate_bollinger_bands,
    calculate_price_momentum,
    check_abnormal_volatility,
    check_volume_surge,
    load_config,
    VolatilitySignal
)
from core.price_fetcher import (
    fetch_domestic_gold_price,
    fetch_international_gold_price,
    fetch_usd_cny_rate,
    calculate_premium_rate,
    get_all_gold_prices
)
from core.state_manager import StateManager


class AnalysisReport:
    """
    深度分析报告生成器（异步版本）
    """
    
    def __init__(self):
        """初始化分析器"""
        self.config = load_config()
        self.market_cal = MarketCalendar()
        self.state_mgr = StateManager()
        self._stream = None
        
        logger.info("[AnalysisReport] 分析器初始化完成")
    
    async def fetch_market_data_with_domestic(
        self,
        gold_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        获取市场数据（包含国内金价）
        
        Args:
            gold_data: 从 get_all_gold_prices() 获取的金价数据
        
        Returns:
            Dict: 包含国内外金价的市场数据
        """
        try:
            stream = create_data_stream(use_mock=False, symbol="GC=F")
            ticks_received: List[TickData] = []
            
            async def collect_ticks():
                async for tick in stream.connect():
                    ticks_received.append(tick)
                    if len(ticks_received) >= 50:
                        break
            
            import time
            await asyncio.wait_for(collect_ticks(), timeout=10.0)
            await stream.stop()
            
            if not ticks_received:
                return None
            
            prices = [tick.price for tick in ticks_received]
            
            return {
                'international_price': gold_data.get('international_price_usd_oz'),
                'domestic_price': gold_data.get('domestic_price_cny_g'),
                'exchange_rate': gold_data.get('exchange_rate'),
                'premium_rate': gold_data.get('premium_rate'),
                'current_price': ticks_received[-1].price,
                'prices': prices,
                'timestamp': time.time()
            }
        
        except asyncio.TimeoutError:
            logger.error("[AnalysisReport] 获取市场数据超时")
            return None
        except Exception as e:
            logger.error(f"[AnalysisReport] 获取市场数据失败：{e}")
            return None
    
    def generate_report(
        self,
        market_data: Dict[str, Any],
        include_signals: bool = True
    ) -> str:
        """
        生成 Markdown 研报（包含国内金价、汇率、溢价率）
        
        Args:
            market_data: 市场数据（包含 domestic_price, exchange_rate, premium_rate）
            include_signals: 是否包含信号分析
        
        Returns:
            str: Markdown 格式的研报
        """
        prices = market_data.get("prices", [])
        current_price = market_data.get("current_price", 0)
        symbol = market_data.get("symbol", "GC=F")
        
        # 获取国内金价数据
        domestic_price = market_data.get("domestic_price")
        exchange_rate = market_data.get("exchange_rate")
        premium_rate = market_data.get("premium_rate")
        
        if len(prices) < 20:
            return "⚠️ 数据不足，无法生成完整报告"
        
        # 计算指标
        atr = calculate_atr_from_ticks(prices, period=14)
        rsi = calculate_rsi(prices, period=14)
        ma20 = calculate_ma(prices, period=20)
        ma50 = calculate_ma(prices, period=50)
        bb = calculate_bollinger_bands(prices, period=20)
        momentum_5 = calculate_price_momentum(prices, period=5)
        momentum_20 = calculate_price_momentum(prices, period=20)
        
        # 构建报告
        report = []
        
        # 标题
        report.append(f"# 📊 金银趋势罗盘研报")
        report.append(f"**标的**: {symbol}  |  **时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # 当前盘面（新增国内金价、汇率、溢价率）
        report.append("## 💰 当前盘面")
        report.append(f"- **国际金价**: ${current_price:.2f}")
        
        if domestic_price:
            report.append(f"- **国内金价 (Au99.99)**: ¥{domestic_price:.2f}/克")
        else:
            report.append("- **国内金价**: 休市中或数据暂时不可用")
        
        if exchange_rate:
            report.append(f"- **USD/CNY 汇率**: {exchange_rate:.4f}")
        
        if premium_rate is not None:
            premium_status = "🟢 溢价" if premium_rate > 0 else "🔴 折价"
            report.append(f"- **内外盘溢价率**: {premium_rate:+.2f}% ({premium_status})")
        
        # 涨跌统计
        if len(prices) >= 2:
            change_1d = current_price - prices[0]
            change_1d_pct = (change_1d / prices[0]) * 100 if prices[0] else 0
            report.append(f"- **24H 变化**: `${change_1d:+.2f}` ({change_1d_pct:+.2f}%)")
        
        # 波动率
        if atr:
            report.append(f"- **ATR(14)**: ${atr:.2f} (波动率基准)")
        report.append("")
        
        # 技术指标
        report.append("## 📈 技术指标")
        
        # RSI
        report.append("### 相对强弱 (RSI)")
        if rsi:
            rsi_status = self._get_rsi_status(rsi)
            report.append(f"- **RSI(14)**: `{rsi:.2f}` - {rsi_status}")
        report.append("")
        
        # 移动平均
        report.append("### 移动平均 (MA)")
        if ma20 and ma50:
            ma_signal = self._get_ma_signal(current_price, ma20, ma50)
            report.append(f"- **MA(20)**: `${ma20:.2f}`")
            report.append(f"- **MA(50)**: `${ma50:.2f}`")
            report.append(f"- **信号**: {ma_signal}")
        report.append("")
        
        # 布林带
        report.append("### 布林带 (Bollinger Bands)")
        if bb:
            upper, mid, lower = bb
            bb_position = self._get_bb_position(current_price, upper, mid, lower)
            report.append(f"- **上轨**: `${upper:.2f}`")
            report.append(f"- **中轨**: `${mid:.2f}`")
            report.append(f"- **下轨**: `${lower:.2f}`")
            report.append(f"- **位置**: {bb_position}")
        report.append("")
        
        # 动量分析
        report.append("## 🚀 动量分析")
        if momentum_5 is not None:
            report.append(f"- **5 周期动量**: `{momentum_5:+.2f}%`")
        if momentum_20 is not None:
            report.append(f"- **20 周期动量**: `{momentum_20:+.2f}%`")
        report.append("")
        
        # 信号汇总
        if include_signals:
            report.append("## 🎯 信号汇总")
            signals = self._collect_signals(current_price, prices, atr, rsi, ma20, ma50, bb)
            report.append(signals)
        
        # 风险提示
        report.append("")
        report.append("## ⚠️ 风险提示")
        report.append("> 本报告仅供参考，不构成投资建议。")
        report.append("> 市场有风险，投资需谨慎。")
        report.append("")
        report.append("---")
        report.append("*Yuffie 贵金属高频监控系统 | 数据驱动决策*")
        
        return "\n".join(report)
    
    def _get_rsi_status(self, rsi: float) -> str:
        """获取 RSI 状态描述"""
        if rsi >= 70:
            return "🔴 超买区（警惕回调）"
        elif rsi <= 30:
            return "🟢 超卖区（可能反弹）"
        elif rsi >= 60:
            return "🟡 偏强区域"
        elif rsi <= 40:
            return "🔵 偏弱区域"
        else:
            return "⚪ 中性区域"
    
    def _get_ma_signal(self, price: float, ma20: float, ma50: float) -> str:
        """获取 MA 信号"""
        if price > ma20 > ma50:
            return "📈 多头排列（强势）"
        elif price < ma20 < ma50:
            return "📉 空头排列（弱势）"
        elif price > ma20:
            return "🟡 站上 20 日线"
        elif price < ma20:
            return "🔵 跌破 20 日线"
        else:
            return "⚪ 震荡整理"
    
    def _get_bb_position(self, price: float, upper: float, mid: float, lower: float) -> str:
        """获取布林带位置"""
        if price >= upper:
            return "🔴 突破上轨（超买）"
        elif price <= lower:
            return "🟢 跌破下轨（超卖）"
        elif price >= mid:
            return "🟡 中轨上方（偏强）"
        else:
            return "🔵 中轨下方（偏弱）"
    
    def _collect_signals(self, price, prices, atr, rsi, ma20, ma50, bb) -> str:
        """收集所有信号"""
        signals = []
        
        if rsi:
            if rsi >= 70:
                signals.append("🔴 RSI 超买")
            elif rsi <= 30:
                signals.append("🟢 RSI 超卖")
        
        if ma20 and ma50:
            if price > ma20 > ma50:
                signals.append("📈 多头排列")
            elif price < ma20 < ma50:
                signals.append("📉 空头排列")
        
        if bb:
            upper, mid, lower = bb
            if price >= upper:
                signals.append("🔴 布林上轨压力")
            elif price <= lower:
                signals.append("🟢 布林下轨支撑")
        
        if not signals:
            return "⚪ 暂无明显信号，市场震荡整理"
        
        return "  ".join(signals)
    
    def close(self):
        """关闭分析器"""
        self.state_mgr.close()


# ==================== AstrBot 指令处理 ====================

async def handle_gold_analysis(event: Optional[AstrMessageEvent] = None) -> str:
    """
    处理 /黄金分析 指令（异步版本，包含国内金价）
    
    Args:
        event: AstrBot 事件对象
    
    Returns:
        str: Markdown 研报
    """
    logger.info("[AnalysisReport] 收到黄金分析请求")
    
    analyzer = AnalysisReport()
    
    try:
        # 异步获取所有金价数据
        gold_data = await get_all_gold_prices()
        
        # 获取市场数据（包含国内金价）
        market_data = await analyzer.fetch_market_data_with_domestic(gold_data)
        
        if not market_data:
            return "⚠️ 获取市场数据失败，请稍后重试"
        
        # 生成报告
        report = analyzer.generate_report(market_data)
        
        return report
    
    except Exception as e:
        logger.error(f"[AnalysisReport] 生成报告失败：{e}")
        return f"⚠️ 分析失败：{e}"
    
    finally:
        analyzer.close()


# ==================== AstrBot 插件注册 ====================

try:
    from astrbot.api import register_command
    
    @register_command("黄金分析", description="获取黄金市场深度分析报告（含国内金价、溢价率）")
    async def gold_analysis_command(event: AstrMessageEvent):
        """黄金分析指令"""
        report = await handle_gold_analysis(event)
        await event.send(report)
        
except ImportError:
    logger.info("[AnalysisReport] 非 AstrBot 环境，跳过指令注册")


# ==================== 使用示例 ====================

if __name__ == "__main__":
    async def main():
        print("="*60)
        print("Yuffie 深度分析报告测试")
        print("="*60)
        
        report = await handle_gold_analysis()
        print("\n" + report)
    
    asyncio.run(main())
