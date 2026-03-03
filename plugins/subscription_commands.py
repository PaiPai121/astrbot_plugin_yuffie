"""
subscription_commands.py - 订阅管理指令

指令:
    /订阅 - 订阅黄金跳水预警
    /取消订阅 - 取消订阅
    /订阅状态 - 查看订阅状态
    /订阅统计 - 查看订阅统计（管理员）
"""

import asyncio
from typing import Optional

# AstrBot 导入
try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent
    from astrbot.api.register import register
    from astrbot.api.message_components import Plain
except ImportError:
    import logging
    logger = logging.getLogger("Yuffie")
    
    class AstrMessageEvent:
        pass
    
    class register:
        @staticmethod
        def command(*args, **kwargs):
            def decorator(func):
                return func
            return decorator
    
    class Plain:
        def __init__(self, text):
            self.text = text

# 订阅管理器
from .subscriber_manager import SubscriberManager


# ==================== 指令处理 ====================

@register.command("订阅", description="订阅黄金跳水预警")
async def subscribe_command(event: AstrMessageEvent):
    """
    /订阅 - 订阅黄金跳水预警
    """
    try:
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or "用户"
        
        mgr = SubscriberManager()
        success = mgr.subscribe(user_id, user_name)
        
        if success:
            await event.send(Plain(
                f"✅ 订阅成功！\n\n"
                f"欢迎您，{user_name}！\n"
                f"当黄金价格出现异常波动（跳水/暴涨）时，\n"
                f"系统会自动推送预警消息给您。\n\n"
                f"⚙️ 冷却时间：30 分钟（同一方向警报）\n"
                f"📊 数据来源：东方财富 + Binance\n\n"
                f"输入 /取消订阅 可随时取消"
            ))
            logger.info(f"[Subscription] 用户 {user_name} ({user_id}) 订阅成功")
        else:
            await event.send(Plain("❌ 订阅失败，请稍后重试"))
        
        mgr.close()
        
    except Exception as e:
        logger.error(f"[Subscription] 订阅失败：{e}")
        await event.send(Plain(f"❌ 订阅失败：{e}"))


@register.command("取消订阅", description="取消黄金跳水预警订阅")
async def unsubscribe_command(event: AstrMessageEvent):
    """
    /取消订阅 - 取消订阅
    """
    try:
        user_id = event.get_sender_id()
        
        mgr = SubscriberManager()
        success = mgr.unsubscribe(user_id)
        
        if success:
            await event.send(Plain(
                f"✅ 取消订阅成功！\n\n"
                f"您已不再接收黄金跳水预警。\n"
                f"输入 /订阅 可重新订阅"
            ))
            logger.info(f"[Subscription] 用户 {user_id} 取消订阅")
        else:
            await event.send(Plain("❌ 取消订阅失败，请稍后重试"))
        
        mgr.close()
        
    except Exception as e:
        logger.error(f"[Subscription] 取消订阅失败：{e}")
        await event.send(Plain(f"❌ 取消订阅失败：{e}"))


@register.command("订阅状态", description="查看订阅状态")
async def subscription_status_command(event: AstrMessageEvent):
    """
    /订阅状态 - 查看订阅状态
    """
    try:
        user_id = event.get_sender_id()
        user_name = event.get_sender_name() or "用户"
        
        mgr = SubscriberManager()
        is_subscribed = mgr.is_subscribed(user_id)
        
        if is_subscribed:
            stats = mgr.get_stats()
            await event.send(Plain(
                f"📊 订阅状态\n\n"
                f"✅ 您已订阅黄金跳水预警\n\n"
                f"👤 用户名：{user_name}\n"
                f"📈 当前活跃订阅用户：{stats['total_active']} 人\n"
                f"🔔 系统累计推送：{stats['total_alerts']} 次\n\n"
                f"⚙️ 预警规则:\n"
                f"- 触发条件：价格波动 > 2.5 × ATR\n"
                f"- 冷却时间：30 分钟\n"
                f"- 监控标的：GC=F (纽约期金)\n\n"
                f"输入 /取消订阅 可取消"
            ))
        else:
            await event.send(Plain(
                f"📊 订阅状态\n\n"
                f"❌ 您尚未订阅黄金跳水预警\n\n"
                f"输入 /订阅 即可订阅\n"
                f"当黄金价格出现异常波动时，\n"
                f"系统会自动推送预警消息给您"
            ))
        
        mgr.close()
        
    except Exception as e:
        logger.error(f"[Subscription] 查询订阅状态失败：{e}")
        await event.send(Plain(f"❌ 查询失败：{e}"))


@register.command("订阅统计", description="查看订阅统计（管理员）")
async def subscription_stats_command(event: AstrMessageEvent):
    """
    /订阅统计 - 查看订阅统计（管理员）
    """
    try:
        # 这里可以添加管理员权限检查
        # if not event.is_admin():
        #     await event.send(Plain("❌ 仅限管理员查看"))
        #     return
        
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
        
        await event.send(Plain(
            f"📊 订阅统计\n\n"
            f"👥 总用户数：{stats['total_users']}\n"
            f"✅ 活跃订阅：{stats['total_active']}\n"
            f"🔔 累计推送：{stats['total_alerts']}\n\n"
            f"📋 订阅用户列表:\n"
            f"{subscriber_list or '暂无订阅用户'}"
        ))
        
        mgr.close()
        
    except Exception as e:
        logger.error(f"[Subscription] 查询订阅统计失败：{e}")
        await event.send(Plain(f"❌ 查询失败：{e}"))


# ==================== 使用示例 ====================

if __name__ == "__main__":
    # 测试
    mgr = SubscriberManager()
    
    # 订阅
    mgr.subscribe("user123", "测试用户")
    
    # 检查订阅
    print(f"是否订阅：{mgr.is_subscribed('user123')}")
    
    # 统计
    stats = mgr.get_stats()
    print(f"统计：{stats}")
    
    mgr.close()
