"""日程创建工具 - 基于任务和约束创建优化日程"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ...models.task import Task, TaskPriority
from ...models.schedule import Schedule, TimeSlot


class ScheduleCreator:
    """日程创建器"""
    
    def __init__(self):
        # 默认工作时间段
        self.default_work_hours = [
            ("09:00", "12:00"),  # 上午
            ("14:00", "18:00")   # 下午
        ]
        
        # 优先级权重
        self.priority_weights = {
            TaskPriority.URGENT_IMPORTANT: 1.0,
            TaskPriority.IMPORTANT: 0.8,
            TaskPriority.URGENT: 0.6,
            TaskPriority.NORMAL: 0.4,
            TaskPriority.LOW: 0.2
        }
    
    def create_optimized_schedule(
        self, 
        tasks: List[Task], 
        date: str,
        constraints: Optional[Dict] = None
    ) -> Schedule:
        """
        创建优化日程
        
        Args:
            tasks: 任务列表
            date: 日程日期
            constraints: 约束条件
            
        Returns:
            优化后的日程
        """
        # 处理约束条件
        constraints = constraints or {}
        available_time = constraints.get('available_time', 480)  # 默认8小时
        work_hours = constraints.get('work_hours', self.default_work_hours)
        
        # 创建基础日程
        schedule = Schedule(date=date, available_time=available_time)
        
        # 添加任务
        for task in tasks:
            schedule.add_task(task)
        
        # 优化任务安排
        self._optimize_task_arrangement(schedule, work_hours)
        
        return schedule
    
    def _optimize_task_arrangement(self, schedule: Schedule, work_hours: List[tuple]):
        """优化任务安排"""
        if not schedule.tasks:
            return
        
        # 按优先级和耗时排序任务
        sorted_tasks = self._sort_tasks_by_priority_and_duration(schedule.tasks)
        
        # 安排时间段
        time_slots = self._create_time_slots(work_hours)
        
        # 分配任务到时间段
        self._assign_tasks_to_time_slots(sorted_tasks, time_slots, schedule)
    
    def _sort_tasks_by_priority_and_duration(self, tasks: List[Task]) -> List[Task]:
        """按优先级和耗时排序任务"""
        def sort_key(task: Task):
            # 优先级权重 + 耗时（分钟）
            priority_score = self.priority_weights.get(task.priority, 0.4)
            duration_score = task.duration_minutes / 60.0  # 转换为小时
            
            # 综合评分（优先级权重更高）
            return -(priority_score * 0.7 + duration_score * 0.3)
        
        return sorted(tasks, key=sort_key)
    
    def _create_time_slots(self, work_hours: List[tuple]) -> List[TimeSlot]:
        """创建时间段"""
        time_slots = []
        
        for start, end in work_hours:
            # 将工作时间划分为45分钟的工作块和5分钟的休息块
            current_time = datetime.strptime(start, '%H:%M')
            end_time = datetime.strptime(end, '%H:%M')
            
            while current_time < end_time:
                # 工作块（45分钟）
                work_end = current_time + timedelta(minutes=45)
                if work_end > end_time:
                    work_end = end_time
                
                time_slots.append(TimeSlot(
                    start_time=current_time.strftime('%H:%M'),
                    end_time=work_end.strftime('%H:%M'),
                    task_id=None
                ))
                
                # 休息块（5分钟），除非是最后一个时间段
                if work_end < end_time:
                    rest_end = work_end + timedelta(minutes=5)
                    if rest_end <= end_time:
                        time_slots.append(TimeSlot(
                            start_time=work_end.strftime('%H:%M'),
                            end_time=rest_end.strftime('%H:%M'),
                            task_id=None
                        ))
                        current_time = rest_end
                    else:
                        current_time = work_end
                else:
                    current_time = work_end
        
        return time_slots
    
    def _assign_tasks_to_time_slots(
        self, 
        tasks: List[Task], 
        time_slots: List[TimeSlot], 
        schedule: Schedule
    ):
        """分配任务到时间段"""
        available_slots = [slot for slot in time_slots if slot.task_id is None]
        
        for task in tasks:
            # 找到适合任务的时间段
            suitable_slots = self._find_suitable_slots_for_task(task, available_slots)
            
            if suitable_slots:
                # 分配第一个合适的时间段
                slot = suitable_slots[0]
                slot.task_id = task.id
                schedule.assign_time_slot(task.id, slot)
                
                # 从可用时间段中移除
                available_slots.remove(slot)
            else:
                # 如果没有合适的时间段，尝试拆分任务
                self._split_and_assign_task(task, available_slots, schedule)
    
    def _find_suitable_slots_for_task(
        self, 
        task: Task, 
        available_slots: List[TimeSlot]
    ) -> List[TimeSlot]:
        """为任务找到合适的时间段"""
        suitable_slots = []
        
        for slot in available_slots:
            slot_duration = slot.duration_minutes()
            
            # 检查时间段是否足够长
            if slot_duration >= task.duration_minutes:
                suitable_slots.append(slot)
            # 如果任务可以拆分，也考虑较短的时间段
            elif self._can_task_be_split(task) and slot_duration >= 30:  # 至少30分钟
                suitable_slots.append(slot)
        
        # 按时间段长度排序（优先使用较长的时间段）
        suitable_slots.sort(key=lambda s: s.duration_minutes(), reverse=True)
        
        return suitable_slots
    
    def _can_task_be_split(self, task: Task) -> bool:
        """检查任务是否可以拆分"""
        # 长任务（超过2小时）可以拆分
        return task.duration_minutes > 120
    
    def _split_and_assign_task(
        self, 
        task: Task, 
        available_slots: List[TimeSlot], 
        schedule: Schedule
    ):
        """拆分并分配任务"""
        if not self._can_task_be_split(task):
            return
        
        # 将任务拆分为多个子任务
        remaining_duration = task.duration_minutes
        sub_task_count = 0
        
        while remaining_duration > 0 and available_slots:
            # 找到最大的可用时间段
            available_slots.sort(key=lambda s: s.duration_minutes(), reverse=True)
            slot = available_slots[0]
            
            # 确定子任务时长
            sub_duration = min(remaining_duration, slot.duration_minutes())
            
            # 创建子任务
            sub_task = Task(
                name=f"{task.name} (部分{sub_task_count + 1})",
                description=task.description,
                duration_minutes=sub_duration,
                priority=task.priority,
                deadline=task.deadline,
                tags=task.tags
            )
            
            # 分配时间段
            slot.task_id = sub_task.id
            schedule.add_task(sub_task)
            schedule.assign_time_slot(sub_task.id, slot)
            
            # 更新剩余时长和可用时间段
            remaining_duration -= sub_duration
            available_slots.remove(slot)
            sub_task_count += 1
    
    def suggest_schedule_improvements(self, schedule: Schedule) -> List[str]:
        """提供日程改进建议"""
        suggestions = []
        
        # 检查时间利用率
        utilization = schedule.total_duration / schedule.available_time
        if utilization < 0.6:
            suggestions.append("时间利用率较低，可以考虑增加任务或调整可用时间")
        elif utilization > 0.9:
            suggestions.append("日程安排过于紧凑，建议留出缓冲时间")
        
        # 检查高优先级任务安排
        high_priority_tasks = [t for t in schedule.tasks 
                              if t.priority in [TaskPriority.URGENT_IMPORTANT, TaskPriority.IMPORTANT]]
        
        if high_priority_tasks:
            # 检查是否所有高优先级任务都有时间段安排
            scheduled_high_priority = [t for t in high_priority_tasks 
                                     if any(slot.task_id == t.id for slot in schedule.time_slots)]
            
            if len(scheduled_high_priority) < len(high_priority_tasks):
                suggestions.append("部分高优先级任务尚未安排具体时间段")
        
        # 检查任务拆分情况
        split_tasks = [t for t in schedule.tasks if "(部分" in t.name]
        if split_tasks:
            suggestions.append(f"有 {len(split_tasks)} 个任务被拆分为多个时间段执行")
        
        return suggestions


# 创建工具函数（用于Nanobot集成）
def create_optimized_schedule(tasks: List[dict], date: str, constraints: dict = None) -> dict:
    """
    创建优化日程（工具函数）
    
    Args:
        tasks: 任务列表（字典格式）
        date: 日程日期
        constraints: 约束条件
        
    Returns:
        {
            "schedule": Schedule,
            "suggestions": List[str],
            "message": str
        }
    """
    creator = ScheduleCreator()
    
    try:
        # 转换任务数据
        task_objects = [Task.from_dict(task) for task in tasks]
        
        # 创建日程
        schedule = creator.create_optimized_schedule(task_objects, date, constraints)
        
        # 生成改进建议
        suggestions = creator.suggest_schedule_improvements(schedule)
        
        return {
            "schedule": schedule.to_dict(),
            "suggestions": suggestions,
            "message": "日程创建成功"
        }
        
    except Exception as e:
        return {
            "schedule": {},
            "suggestions": [],
            "message": f"日程创建失败: {str(e)}"
        }


# 测试函数
if __name__ == "__main__":
    # 测试日程创建器
    from ...models.task import TaskCreateRequest
    
    # 创建测试任务
    test_tasks = [
        TaskCreateRequest(
            name="准备学术报告",
            description="整理研究数据，制作PPT",
            duration_minutes=180,
            priority=TaskPriority.URGENT_IMPORTANT
        ),
        TaskCreateRequest(
            name="代码review",
            description="审查团队代码",
            duration_minutes=60,
            priority=TaskPriority.IMPORTANT
        ),
        TaskCreateRequest(
            name="健身",
            description="健身房锻炼",
            duration_minutes=90,
            priority=TaskPriority.NORMAL
        )
    ]
    
    creator = ScheduleCreator()
    schedule = creator.create_optimized_schedule(test_tasks, "2024-04-08")
    
    print("=== 创建的日程 ===")
    print(f"日期: {schedule.date}")
    print(f"总耗时: {schedule.total_duration}分钟")
    print(f"效率评分: {schedule.efficiency_score}")
    
    print("\n任务安排:")
    for task in schedule.tasks:
        assigned_slots = [slot for slot in schedule.time_slots if slot.task_id == task.id]
        if assigned_slots:
            slot_info = ", ".join([f"{slot.start_time}-{slot.end_time}" for slot in assigned_slots])
            print(f"  - {task.name}: {slot_info}")
        else:
            print(f"  - {task.name}: 未安排时间段")
    
    # 生成改进建议
    suggestions = creator.suggest_schedule_improvements(schedule)
    if suggestions:
        print("\n改进建议:")
        for suggestion in suggestions:
            print(f"  - {suggestion}")