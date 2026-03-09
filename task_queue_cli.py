#!/usr/bin/env python3
"""
TaskQueue CLI - 任务队列命令行工具

用法:
    python3 task_queue_cli.py submit <task_name> [options]
    python3 task_queue_cli.py status <task_id>
    python3 task_queue_cli.py list [options]
    python3 task_queue_cli.py stats
    python3 task_queue_cli.py cancel <task_id>
    python3 task_queue_cli.py cleanup [days]

示例:
    # 提交重启服务任务
    python3 task_queue_cli.py submit restart_service --service nanobot --user 460967411
    
    # 提交通用命令
    python3 task_queue_cli.py submit generic_command --command "ls -la" --user 460967411
    
    # 查看任务状态
    python3 task_queue_cli.py status abc12345
    
    # 列出用户任务
    python3 task_queue_cli.py list --user 460967411
    
    # 查看统计
    python3 task_queue_cli.py stats
"""

import argparse
import json
import sys
import time
from pathlib import Path

# 添加 scripts 目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from task_queue import (
    task_queue, TaskQueue, submit_task, get_task_status, 
    list_tasks, TaskStatus
)


def cmd_submit(args):
    """提交任务"""
    metadata = {}
    
    # 根据任务类型解析参数
    if args.task_name == "restart_service":
        metadata["service"] = args.service or "nanobot"
    elif args.task_name == "generic_command":
        metadata["command"] = args.command
        metadata["timeout"] = args.timeout or 60
    else:
        # 通用参数解析 (key=value 格式)
        if args.params:
            for param in args.params:
                if "=" in param:
                    key, value = param.split("=", 1)
                    try:
                        # 尝试解析 JSON
                        metadata[key] = json.loads(value)
                    except:
                        metadata[key] = value
    
    task_id = submit_task(
        name=args.task_name,
        metadata=metadata,
        user_id=args.user,
        channel=args.channel
    )
    
    print(f"✅ 任务已提交: {task_id}")
    print(f"   任务名称: {args.task_name}")
    print(f"   参数: {json.dumps(metadata, ensure_ascii=False)}")
    
    # 启动队列开始处理
    task_queue.start()
    
    # 如果需要等待完成
    if args.wait:
        print("\n⏳ 等待任务完成...")
        for i in range(args.wait):
            time.sleep(1)
            task = get_task_status(task_id)
            if task.status in ["completed", "failed"]:
                break
            print(f"   状态: {task.status}", end="\r")
        
        task = get_task_status(task_id)
        print(f"\n\n📊 最终状态: {task.status}")
        if task.result:
            print(f"📝 结果: {task.result}")
        if task.error:
            print(f"❌ 错误: {task.error}")
    
    return 0


def cmd_status(args):
    """查看任务状态"""
    task = get_task_status(args.task_id)
    
    if not task:
        print(f"❌ 未找到任务: {args.task_id}")
        return 1
    
    print(f"📋 任务详情")
    print(f"   ID: {task.id}")
    print(f"   名称: {task.name}")
    print(f"   状态: {task.status}")
    print(f"   创建: {task.created_at}")
    
    if task.started_at:
        print(f"   开始: {task.started_at}")
    if task.completed_at:
        print(f"   完成: {task.completed_at}")
    
    if task.result:
        print(f"   结果: {task.result}")
    if task.error:
        print(f"   错误: {task.error}")
    
    if task.metadata:
        print(f"   参数: {task.metadata}")
    
    if task.user_id:
        print(f"   用户: {task.user_id}")
    
    return 0


def cmd_list(args):
    """列出任务"""
    if args.status:
        tasks = task_queue.get_tasks_by_status(args.status)
    elif args.user:
        tasks = list_tasks(user_id=args.user, limit=args.limit)
    else:
        tasks = list_tasks(limit=args.limit)
    
    if not tasks:
        print("📭 没有任务")
        return 0
    
    print(f"📋 任务列表 (共 {len(tasks)} 个)")
    print("-" * 80)
    
    for task in tasks:
        status_icon = {
            "pending": "⏳",
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "🚫"
        }.get(task.status, "?")
        
        print(f"{status_icon} {task.id} | {task.name:20} | {task.status:10} | {task.created_at[:19]}")
    
    return 0


def cmd_stats(args):
    """查看统计"""
    stats = task_queue.get_stats()
    
    print("📊 任务队列统计")
    print("-" * 40)
    print(f"⏳ 待处理: {stats.get('pending', 0)}")
    print(f"🔄 执行中: {stats.get('running', 0)}")
    print(f"✅ 已完成: {stats.get('completed', 0)}")
    print(f"❌ 失败:   {stats.get('failed', 0)}")
    print(f"🚫 取消:   {stats.get('cancelled', 0)}")
    print(f"📦 队列:   {stats.get('queue_size', 0)}")
    
    return 0


def cmd_cancel(args):
    """取消任务"""
    success = task_queue.cancel(args.task_id)
    
    if success:
        print(f"✅ 任务已取消: {args.task_id}")
        return 0
    else:
        print(f"❌ 无法取消任务: {args.task_id}")
        print("   (任务可能已完成或不存在)")
        return 1


def cmd_cleanup(args):
    """清理旧任务"""
    days = args.days or 30
    deleted = task_queue.cleanup(days)
    print(f"✅ 已清理 {deleted} 个 {days} 天前的任务")
    return 0


def cmd_start(args):
    """启动任务队列"""
    task_queue.start()
    print("✅ 任务队列已启动")
    return 0


def cmd_stop(args):
    """停止任务队列"""
    task_queue.stop()
    print("✅ 任务队列已停止")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="TaskQueue CLI - 任务队列管理工具"
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # submit 命令
    submit_parser = subparsers.add_parser("submit", help="提交任务")
    submit_parser.add_argument("task_name", help="任务名称")
    submit_parser.add_argument("-s", "--service", help="服务名 (restart_service用)")
    submit_parser.add_argument("-c", "--command", help="命令 (generic_command用)")
    submit_parser.add_argument("-t", "--timeout", type=int, help="超时时间")
    submit_parser.add_argument("-u", "--user", help="用户ID")
    submit_parser.add_argument("-ch", "--channel", help="通知渠道")
    submit_parser.add_argument("-p", "--params", nargs="+", help="额外参数 (key=value)")
    submit_parser.add_argument("-w", "--wait", type=int, help="等待完成(秒)")
    submit_parser.set_defaults(func=cmd_submit)
    
    # status 命令
    status_parser = subparsers.add_parser("status", help="查看任务状态")
    status_parser.add_argument("task_id", help="任务ID")
    status_parser.set_defaults(func=cmd_status)
    
    # list 命令
    list_parser = subparsers.add_parser("list", help="列出任务")
    list_parser.add_argument("-u", "--user", help="用户ID")
    list_parser.add_argument("-s", "--status", help="任务状态")
    list_parser.add_argument("-l", "--limit", type=int, default=20, help="显示数量")
    list_parser.set_defaults(func=cmd_list)
    
    # stats 命令
    stats_parser = subparsers.add_parser("stats", help="查看统计")
    stats_parser.set_defaults(func=cmd_stats)
    
    # cancel 命令
    cancel_parser = subparsers.add_parser("cancel", help="取消任务")
    cancel_parser.add_argument("task_id", help="任务ID")
    cancel_parser.set_defaults(func=cmd_cancel)
    
    # cleanup 命令
    cleanup_parser = subparsers.add_parser("cleanup", help="清理旧任务")
    cleanup_parser.add_argument("days", type=int, help="保留天数")
    cleanup_parser.set_defaults(func=cmd_cleanup)
    
    # start 命令
    start_parser = subparsers.add_parser("start", help="启动任务队列")
    start_parser.set_defaults(func=cmd_start)
    
    # stop 命令
    stop_parser = subparsers.add_parser("stop", help="停止任务队列")
    stop_parser.set_defaults(func=cmd_stop)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
