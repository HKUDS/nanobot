"""Date Arrange 演示脚本"""

from date_arrange.skills.planner.task_parser import parse_user_goal
from date_arrange.skills.planner.schedule_creator import create_optimized_schedule
from date_arrange.models.task import Task


def demo():
    """演示 Date Arrange 功能"""
    print("=== Date Arrange 演示 ===")
    print("=" * 50)
    
    # 演示用例
    test_cases = [
        {
            "name": "学术工作安排",
            "input": "需要准备下周的学术报告，还要完成代码review，另外要安排健身时间"
        },
        {
            "name": "软件开发任务", 
            "input": "今天要完成代码开发、写文档、团队会议"
        },
        {
            "name": "紧急任务处理",
            "input": "紧急处理客户投诉，重要项目会议安排在明天下午"
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n[演示 {i}] {test_case['name']}")
        print("-" * 30)
        
        # 解析用户输入
        print(f"用户输入: {test_case['input']}")
        
        result = parse_user_goal(test_case['input'])
        tasks = [Task.from_dict(task_data) for task_data in result["tasks"]]
        
        print(f"[成功] {result['message']}")
        print("解析出的任务:")
        for task in tasks:
            print(f"  - {task.name} (优先级: {task.priority}, 耗时: {task.duration_minutes}分钟)")
        
        # 创建日程
        if tasks:
            task_dicts = [task.to_dict() for task in tasks]
            schedule_result = create_optimized_schedule(task_dicts, "2024-04-08")
            
            if schedule_result['schedule']:
                schedule_data = schedule_result['schedule']
                print(f"\n优化日程:")
                print(f"  日期: {schedule_data['date']}")
                print(f"  总耗时: {schedule_data['total_duration']}分钟")
                print(f"  效率评分: {schedule_data['efficiency_score']}")
                
                if schedule_result['suggestions']:
                    print(f"\n改进建议:")
                    for suggestion in schedule_result['suggestions']:
                        print(f"   - {suggestion}")
        
        print("-" * 30)
    
    print("\n[完成] 演示完成！")
    print("Date Arrange 已成功解析自然语言输入并创建优化日程。")


def integration_demo():
    """集成演示 - 模拟 Nanobot 集成"""
    print("\n=== Nanobot 集成演示 ===")
    print("=" * 50)
    
    # 模拟用户与 Nanobot 的对话
    conversation = [
        {"role": "user", "content": "帮我安排一下明天的工作日程"},
        {"role": "assistant", "content": "好的，请告诉我您明天需要完成哪些任务？"},
        {"role": "user", "content": "需要准备学术报告、完成代码review、安排团队会议"}
    ]
    
    print("对话记录:")
    for msg in conversation:
        print(f"  {msg['role']}: {msg['content']}")
    
    # 使用 Date Arrange 处理用户输入
    user_input = conversation[2]["content"]
    result = parse_user_goal(user_input)
    
    print(f"\nDate Arrange 处理结果:")
    print(f"  - {result['message']}")
    
    if result['tasks']:
        tasks = [Task.from_dict(task_data) for task_data in result["tasks"]]
        print("  - 解析出的任务:")
        for task in tasks:
            print(f"    - {task.name} ({task.duration_minutes}分钟, {task.priority})")
        
        # 创建日程
        task_dicts = [task.to_dict() for task in tasks]
        schedule_result = create_optimized_schedule(task_dicts, "2024-04-09")
        
        if schedule_result['schedule']:
            schedule_data = schedule_result['schedule']
            print(f"\n  优化日程已创建:")
            print(f"    - 日期: {schedule_data['date']}")
            print(f"    - 总耗时: {schedule_data['total_duration']}分钟")
            print(f"    - 效率评分: {schedule_data['efficiency_score']}")
    
    print("\n[完成] 集成演示完成！")
    print("Date Arrange 可以无缝集成到 Nanobot 对话流程中。")


if __name__ == "__main__":
    demo()
    integration_demo()