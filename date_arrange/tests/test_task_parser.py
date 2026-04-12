"""任务解析器测试"""

import pytest
from ..skills.planner.task_parser import TaskParser
from ..models.task import TaskPriority


class TestTaskParser:
    """任务解析器测试类"""
    
    def setup_method(self):
        """测试前设置"""
        self.parser = TaskParser()
    
    def test_parse_simple_task(self):
        """测试简单任务解析"""
        user_input = "准备学术报告"
        tasks = self.parser.parse_natural_language(user_input)
        
        assert len(tasks) == 1
        task = tasks[0]
        assert task.name == "准备学术报告"
        assert task.duration_minutes > 0
        assert task.priority == TaskPriority.NORMAL
    
    def test_parse_multiple_tasks(self):
        """测试多任务解析"""
        user_input = "需要准备下周的学术报告，还要完成代码review，另外要安排健身时间"
        tasks = self.parser.parse_natural_language(user_input)
        
        assert len(tasks) >= 2
        
        # 检查任务名称
        task_names = [task.name for task in tasks]
        assert any("学术报告" in name for name in task_names)
        assert any("代码review" in name or "代码" in name for name in task_names)
    
    def test_parse_with_priority(self):
        """测试带优先级的任务解析"""
        user_input = "紧急处理客户投诉，重要项目会议安排在明天下午"
        tasks = self.parser.parse_natural_language(user_input)
        
        assert len(tasks) >= 1
        
        # 检查优先级
        priorities = [task.priority for task in tasks]
        assert TaskPriority.URGENT in priorities or TaskPriority.IMPORTANT in priorities
    
    def test_parse_with_duration(self):
        """测试带时长的任务解析"""
        user_input = "需要2小时完成报告，30分钟健身"
        tasks = self.parser.parse_natural_language(user_input)
        
        assert len(tasks) >= 1
        
        # 检查时长
        for task in tasks:
            if "报告" in task.name:
                assert task.duration_minutes == 120  # 2小时
            elif "健身" in task.name:
                assert task.duration_minutes == 30  # 30分钟
    
    def test_parse_empty_input(self):
        """测试空输入"""
        tasks = self.parser.parse_natural_language("")
        assert len(tasks) == 0
    
    def test_extract_task_name(self):
        """测试任务名称提取"""
        description = "明天上午9点需要2小时完成重要的学术报告准备"
        task_name = self.parser._extract_task_name(description)
        
        # 应该去除时间信息和优先级词汇
        assert "明天" not in task_name
        assert "9点" not in task_name
        assert "2小时" not in task_name
        assert "重要" not in task_name
        assert "学术报告" in task_name or "报告" in task_name
    
    def test_extract_duration(self):
        """测试时长提取"""
        test_cases = [
            ("需要2小时完成", 120),
            ("30分钟健身", 30),
            ("1个半小时会议", 90),
            ("半天工作", 240),
            ("简单任务", 30)  # 默认值
        ]
        
        for description, expected_duration in test_cases:
            duration = self.parser._extract_duration(description)
            assert duration == expected_duration, f"{description} 应该返回 {expected_duration}"
    
    def test_determine_priority(self):
        """测试优先级确定"""
        test_cases = [
            ("紧急重要的任务", TaskPriority.URGENT_IMPORTANT),
            ("重要但不紧急", TaskPriority.IMPORTANT),
            ("紧急但不重要", TaskPriority.URGENT),
            ("普通任务", TaskPriority.NORMAL),
            ("低优先级任务", TaskPriority.LOW)
        ]
        
        for description, expected_priority in test_cases:
            priority = self.parser._determine_priority(description)
            assert priority == expected_priority, f"{description} 应该返回 {expected_priority}"


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])