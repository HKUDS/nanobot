"""Date Arrange 基本使用示例"""

from date_arrange.skills.planner.task_parser import parse_user_goal
from date_arrange.skills.planner.schedule_creator import create_optimized_schedule
from date_arrange.models.task import Task


def basic_usage_example():
    """基本使用示例"""
    print("=== Date Arrange 基本使用示例 ===\n")
    
    # 1. 解析用户自然语言输入
    user_input = "我需要准备下周的学术报告，还要完成代码review，另外要安排健身时间"
    print(f"用户输入: {user_input}")
    
    result = parse_user_goal(user_input)
    tasks = [Task.from_dict(task_data) for task_data in result["tasks"]]
    
    print(f"\n解析结果: {result['message']}")
    print("解析出的任务:")
    for task in tasks:
        print(f"  - {task.name} (优先级: {task.priority}, 耗时: {task.duration_minutes}分钟)")
    
    # 2. 创建优化日程
    print("\n=== 创建优化日程 ===")
    
    task_dicts = [task.to_dict() for task in tasks]
    schedule_result = create_optimized_schedule(task_dicts, "2024-04-08")
    
    print(f"日程创建: {schedule_result['message']}")
    
    if schedule_result['schedule']:
        schedule_data = schedule_result['schedule']
        print(f"日期: {schedule_data['date']}")
        print(f"总耗时: {schedule_data['total_duration']}分钟")
        print(f"效率评分: {schedule_data['efficiency_score']}")
        
        # 显示改进建议
        if schedule_result['suggestions']:
            print("\n改进建议:")
            for suggestion in schedule_result['suggestions']:
                print(f"  - {suggestion}")


def advanced_usage_example():
    """高级使用示例"""
    print("\n=== 高级使用示例 ===\n")
    
    # 使用约束条件创建日程
    constraints = {
        'available_time': 360,  # 6小时可用时间
        'work_hours': [
            ("09:00", "12:00"),  # 上午工作时间
            ("14:00", "17:00")   # 下午工作时间
        ]
    }
    
    user_input = "今天要完成代码开发、写文档、团队会议"
    print(f"用户输入: {user_input}")
    
    # 解析任务
    result = parse_user_goal(user_input)
    tasks = [Task.from_dict(task_data) for task_data in result["tasks"]]
    
    print("\n解析出的任务:")
    for task in tasks:
        print(f"  - {task.name} (优先级: {task.priority}, 耗时: {task.duration_minutes}分钟)")
    
    # 使用约束创建日程
    task_dicts = [task.to_dict() for task in tasks]
    schedule_result = create_optimized_schedule(task_dicts, "2024-04-08", constraints)
    
    print(f"\n日程创建: {schedule_result['message']}")
    
    if schedule_result['schedule']:
        schedule_data = schedule_result['schedule']
        print(f"可用时间: {schedule_data['available_time']}分钟")
        print(f"时间利用率: {schedule_data['total_duration'] / schedule_data['available_time']:.1%}")


if __name__ == "__main__":
    basic_usage_example()
    advanced_usage_example()