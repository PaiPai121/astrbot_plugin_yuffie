"""
alert_levels.py - 多级预警机制

实现:
    - Level 1 (提醒): 普通波动，仅记录
    - Level 2 (预警): 达到 ATR 阈值，群内推送
    - Level 3 (熔断/跳水): 极短时间剧烈跌幅，高强度提醒
"""

from enum import Enum
from typing import Optional, Dict, Any


class AlertLevel(Enum):
    """预警等级"""
    LEVEL1_INFO = 1       # 提醒 - 普通波动
    LEVEL2_WARNING = 2    # 预警 - 达到 ATR 阈值
    LEVEL3_CRITICAL = 3   # 熔断/跳水 - 剧烈跌幅


class AlertManager:
    """预警管理器"""
    
    def __init__(self):
        # 阈值配置
        self.thresholds = {
            'level1_k': 1.0,      # Level 1: 1.0 * ATR
            'level2_k': 2.5,      # Level 2: 2.5 * ATR
            'level3_k': 4.0,      # Level 3: 4.0 * ATR (剧烈跌幅)
            'level3_timeframe': 5 # Level 3: 5 分钟内
        }
    
    def set_threshold(self, level: str, value: float) -> bool:
        """
        动态调整阈值
        
        Args:
            level: 等级 ('level1_k', 'level2_k', 'level3_k')
            value: 新的 k 值
        
        Returns:
            bool: 是否成功
        """
        if level in self.thresholds:
            self.thresholds[level] = value
            return True
        return False
    
    def get_threshold(self, level: str) -> Optional[float]:
        """获取阈值"""
        return self.thresholds.get(level)
    
    def evaluate_alert_level(
        self,
        price_change_pct: float,
        atr: float,
        current_price: float
    ) -> AlertLevel:
        """
        评估预警等级
        
        Args:
            price_change_pct: 价格变化百分比
            atr: ATR 值
            current_price: 当前价格
        
        Returns:
            AlertLevel: 预警等级
        """
        if atr <= 0:
            return AlertLevel.LEVEL1_INFO
        
        # 计算 ATR 倍数
        atr_multiple = abs(price_change_pct) / (atr / current_price * 100)
        
        # 判断等级
        if atr_multiple >= self.thresholds['level3_k']:
            return AlertLevel.LEVEL3_CRITICAL
        elif atr_multiple >= self.thresholds['level2_k']:
            return AlertLevel.LEVEL2_WARNING
        elif atr_multiple >= self.thresholds['level1_k']:
            return AlertLevel.LEVEL1_INFO
        else:
            return AlertLevel.LEVEL1_INFO
    
    def get_alert_message(
        self,
        level: AlertLevel,
        current_price: float,
        price_change: float,
        price_change_pct: float,
        atr: float
    ) -> str:
        """
        生成预警消息
        
        Args:
            level: 预警等级
            current_price: 当前价格
            price_change: 价格变化
            price_change_pct: 价格变化百分比
            atr: ATR 值
        
        Returns:
            str: 预警消息
        """
        if level == AlertLevel.LEVEL3_CRITICAL:
            icon = "🚨🚨🚨"
            title = "【熔断/跳水警报】"
            urgency = "🔴 极高"
        elif level == AlertLevel.LEVEL2_WARNING:
            icon = "🚨"
            title = "【预警】"
            urgency = "🟠 高"
        else:
            icon = "ℹ️"
            title = "【提醒】"
            urgency = "🟡 中"
        
        direction = "📈 上涨" if price_change > 0 else "📉 下跌"
        
        message = f"""{icon} {title}

{direction} 金价异动

💰 当前价格：${current_price:.2f}
📊 变化：{price_change:+.2f} ({price_change_pct:+.2f}%)
📈 ATR(14): ${atr:.2f}
⚡ 紧急程度：{urgency}

⚠️ 市场有风险，投资需谨慎
"""
        
        return message


# 全局预警管理器实例
alert_manager = AlertManager()
