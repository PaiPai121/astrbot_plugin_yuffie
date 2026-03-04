"""
subscription_commands.py - 订阅管理指令（辅助函数）

这些函数被 main.py 中的命令调用，不直接注册为 AstrBot 命令
"""

import asyncio
from typing import Optional

# AstrBot 导入
try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.message_components import Plain
except ImportError:
    import logging
    logger = logging.getLogger("Yuffie")

    class AstrMessageEvent:
        pass

    class Plain:
        def __init__(self, text):
            self.text = text

# 订阅管理器
from .subscriber_manager import SubscriberManager


# ==================== 指令处理辅助函数 ====================

async def subscribe_command(event: AstrMessageEvent):
    """
    订阅黄金跳水预警（辅助函数，被 main.py 调用）
    """
    try:
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or "用户"
        
        mgr = SubscriberManager()
        success = mgr.subscribe(user_id, user_name)
        mgr.close()
        
        if success:
            logger.info(f"[Subscription] 用户 {user_name} ({user_id}) 订阅成功")
        
    except Exception as e:
        logger.error(f"[Subscription] 订阅失败：{e}")
        raise

async def unsubscribe_command(event: AstrMessageEvent):
    """
    取消订阅（辅助函数，被 main.py 调用）
    """
    try:
        user_id = event.get_sender_id()
        
        mgr = SubscriberManager()
        success = mgr.unsubscribe(user_id)
        mgr.close()
        
        if success:
            logger.info(f"[Subscription] 用户 {user_id} 取消订阅成功")
        
    except Exception as e:
        logger.error(f"[Subscription] 取消订阅失败：{e}")
        raise

async def subscription_status_command(event: AstrMessageEvent):
    """
    查看订阅状态（辅助函数，被 main.py 调用）
    返回消息字符串
    """
    try:
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or "用户"

        mgr = SubscriberManager()
        is_subscribed = mgr.is_subscribed(user_id)

        if is_subscribed:
            stats = mgr.get_stats()
            result_msg = (
                f"📊 订阅状态\n\n"
                f"✅ 您已订阅黄金跳水预警\n\n"
                f"👤 用户名：{user_name}\n"
                f"📈 当前活跃订阅用户：{stats['total_active']} 人\n"
                f"🔔 系统累计推送：{stats['total_alerts']} 次\n\n"
                f"⚙️ 预警规则:\n"
                f"- 触发条件：价格波动 > 2.5 × ATR\n"
                f"- 冷却时间：30 分钟\n"
                f"- 监控标的：GC=F (纽约期金)\n\n"
                f"输入 /金价取消订阅 可取消"
            )
        else:
            result_msg = (
                f"📊 订阅状态\n\n"
                f"❌ 您尚未订阅黄金跳水预警\n\n"
                f"输入 /金价订阅 即可订阅\n"
                f"当黄金价格出现异常波动时，\n"
                f"系统会自动推送预警消息给您"
            )

        mgr.close()

        return result_msg

    except Exception as e:
        logger.error(f"[Subscription] 查询订阅状态失败：{e}")
        raise

async def subscription_stats_command(event: AstrMessageEvent):
    """
    查看订阅统计（管理员）（辅助函数，被 main.py 调用）
    返回消息字符串
    """
    try:
        mgr = SubscriberManager()
        stats = mgr.get_stats()
        subscribers = mgr.get_all_subscribers()

        # 构建订阅用户列表
        subscriber_list = "\n".join([
            f"- {s['user_name']} ({s['user_id']}) - 收到 {s['alert_count']} 次警报"
            for s in subscribers[:10]  # 只显示前 10 个
        ])

        if len(subscribers) > 10:
            subscriber_list += f"\n... 还有 {len(subscribers) - 10} 位用户"

        result_msg = (
            f"📊 订阅统计\n\n"
            f"👥 总用户数：{stats['total_users']}\n"
            f"✅ 活跃订阅：{stats['total_active']}\n"
            f"🔔 累计推送：{stats['total_alerts']}\n\n"
            f"📋 订阅用户列表:\n"
            f"{subscriber_list or '暂无订阅用户'}"
        )

        mgr.close()

        return result_msg

    except Exception as e:
        logger.error(f"[Subscription] 查询订阅统计失败：{e}")
        raise
