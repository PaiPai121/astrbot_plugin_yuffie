#!/usr/bin/env python3
"""
test_cli.py - AstrBot 命令行交互模拟器

使用方法:
    python test_cli.py
    
然后可以输入指令与 Bot 交互
"""

import asyncio
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)


class MockEvent:
    """模拟 AstrBot 事件"""
    
    def __init__(self, user_id="test_user", user_name="测试用户"):
        self.user_id = user_id
        self.user_name = user_name
    
    def get_sender_id(self):
        return self.user_id
    
    def get_sender_name(self):
        return self.user_name
    
    async def send(self, message):
        """发送消息"""
        text = message.text if hasattr(message, 'text') else str(message)
        print(f"\n{'='*60}")
        print(f"🤖 Bot 回复:")
        print(f"{'='*60}")
        print(text)
        print(f"{'='*60}\n")


async def main():
    """主函数"""
    print("\n" + "="*60)
    print("   Yuffie AstrBot 命令行交互模拟器")
    print("="*60)
    print("\n💡 提示：输入指令后按回车，输入 /quit 退出\n")
    
    # 加载指令
    try:
        from plugins.subscription_commands import (
            subscribe_command,
            unsubscribe_command,
            subscription_status_command,
            subscription_stats_command
        )
        from plugins.analysis_report import handle_gold_analysis
        
        commands = {
            "/订阅": subscribe_command,
            "/取消订阅": unsubscribe_command,
            "/订阅状态": subscription_status_command,
            "/订阅统计": subscription_stats_command,
            "/黄金分析": handle_gold_analysis,
        }
        
        print("✅ 指令加载成功\n")
        
    except Exception as e:
        print(f"❌ 指令加载失败：{e}")
        print("   请确保已安装所有依赖\n")
        return
    
    # 显示帮助
    print("""
╔══════════════════════════════════════════════════════════╗
║                    可用指令                               ║
╠══════════════════════════════════════════════════════════╣
║  /订阅          - 订阅黄金跳水预警                        ║
║  /取消订阅      - 取消订阅                               ║
║  /订阅状态      - 查看订阅状态                           ║
║  /订阅统计      - 查看订阅统计（管理员）                  ║
║  /黄金分析      - 获取黄金市场深度分析报告                 ║
║  /help          - 显示帮助                               ║
║  /quit          - 退出                                   ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    event = MockEvent("test_user_001", "测试用户")
    
    while True:
        try:
            # 获取用户输入
            cmd = input("📝 请输入指令：").strip()
            
            if not cmd:
                continue
            
            # 退出
            if cmd.lower() in ["/quit", "quit", "exit", "q"]:
                print("\n👋 再见！\n")
                break
            
            # 帮助
            if cmd.lower() == "/help":
                print("""
╔══════════════════════════════════════════════════════════╗
║                    可用指令                               ║
╠══════════════════════════════════════════════════════════╣
║  /订阅          - 订阅黄金跳水预警                        ║
║  /取消订阅      - 取消订阅                               ║
║  /订阅状态      - 查看订阅状态                           ║
║  /订阅统计      - 查看订阅统计（管理员）                  ║
║  /黄金分析      - 获取黄金市场深度分析报告                 ║
║  /help          - 显示帮助                               ║
║  /quit          - 退出                                   ║
╚══════════════════════════════════════════════════════════╝
                """)
                continue
            
            # 查找并执行指令
            if cmd in commands:
                try:
                    await commands[cmd](event)
                except Exception as e:
                    print(f"\n❌ 指令执行失败：{e}\n")
            else:
                print(f"\n⚠️ 未知指令：{cmd}")
                print("   输入 /help 查看可用指令\n")
                
        except KeyboardInterrupt:
            print("\n\n⚠️ 中断退出\n")
            break
        except Exception as e:
            print(f"\n❌ 错误：{e}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ 中断退出\n")
    except Exception as e:
        print(f"\n❌ 启动失败：{e}\n")
        import traceback
        traceback.print_exc()
