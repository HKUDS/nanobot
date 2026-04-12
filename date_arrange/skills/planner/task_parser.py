"""任务解析工具 - 将自然语言输入转化为结构化任务"""

import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from ...models.task import Task, TaskPriority, TaskCreateRequest


class TaskParser:
    """任务解析器"""
    
    def __init__(self):
        # 关键词映射
        self.priority_keywords = {
            'urgent_important': ['紧急重要', '非常重要', '必须完成', '关键任务'],
            'important': ['重要', '需要完成', '应该做', '主要任务'],
            'urgent': ['紧急', '马上', '立刻', '尽快'],
            'normal': ['一般', '普通', '常规'],
            'low': ['低优先级', '不着急', '有空再做']
        }
        
        # 时间单位映射
        self.time_units = {
            '小时': 60,
            '小时半': 90,
            '半小时': 30,
            '分钟': 1,
            'minute': 1,
            'hour': 60
        }
    
    def parse_natural_language(self, user_input: str, context: Optional[Dict] = None) -> List[Task]:
        """
        解析自然语言输入，返回结构化任务列表
        
        Args:
            user_input: 用户自然语言描述
            context: 上下文信息（可选）
            
        Returns:
            解析后的任务列表
        """
        # 预处理输入
        cleaned_input = self._preprocess_input(user_input)
        
        # 分割任务描述
        task_descriptions = self._split_task_descriptions(cleaned_input)
        
        # 解析每个任务
        tasks = []
        for desc in task_descriptions:
            task = self._parse_single_task(desc, context)
            if task:
                tasks.append(task)
        
        return tasks
    
    def _preprocess_input(self, text: str) -> str:
        """预处理输入文本"""
        # 去除多余空格
        text = re.sub(r'\s+', ' ', text.strip())
        
        # 标准化标点符号
        text = text.replace('，', ',').replace('；', ';').replace('。', '.')
        
        return text
    
    def _split_task_descriptions(self, text: str) -> List[str]:
        """分割任务描述"""
        # 使用多种分隔符分割
        separators = ['，', ',', ';', '；', '然后', '还要', '另外', '以及', '和']
        
        # 构建正则表达式模式
        pattern = '|'.join([re.escape(sep) for sep in separators])
        
        # 分割并过滤空字符串
        parts = [part.strip() for part in re.split(pattern, text) if part.strip()]
        
        # 如果只有一个部分，尝试进一步分割
        if len(parts) == 1:
            parts = self._further_split_single_task(parts[0])
        
        # 过滤掉过短的部分（少于3个字符）
        parts = [part for part in parts if len(part) >= 3]
        
        return parts
    
    def _further_split_single_task(self, text: str) -> List[str]:
        """进一步分割单个任务描述"""
        # 尝试根据连接词分割
        connectors = ['并且', '而且', '同时', '还要', '另外', '以及', '和']
        
        for connector in connectors:
            if connector in text:
                parts = text.split(connector)
                return [part.strip() for part in parts if part.strip()]
        
        # 尝试根据标点符号分割
        punctuation_patterns = ['，', ',', ';', '；']
        for punctuation in punctuation_patterns:
            if punctuation in text:
                parts = text.split(punctuation)
                if len(parts) > 1:
                    return [part.strip() for part in parts if part.strip()]
        
        # 如果包含多个动词，可能包含多个任务
        verbs = ['准备', '完成', '做', '处理', '安排', '学习', '写', '读', '开发', '开会', '会议']
        verb_count = sum(1 for verb in verbs if verb in text)
        
        if verb_count > 1:
            # 尝试根据动词分割
            pattern = '|'.join([re.escape(verb) for verb in verbs])
            parts = re.split(f'({pattern})', text)
            
            # 重组部分
            result = []
            current = ""
            for part in parts:
                if part.strip() and part in verbs:
                    if current:
                        result.append(current.strip())
                    current = part
                else:
                    current += part
            
            if current:
                result.append(current.strip())
            
            if len(result) > 1:
                return result
        
        return [text]
    
    def _parse_single_task(self, description: str, context: Optional[Dict]) -> Optional[Task]:
        """解析单个任务描述"""
        try:
            # 提取任务名称
            task_name = self._extract_task_name(description)
            
            # 提取预计耗时
            duration = self._extract_duration(description)
            
            # 确定优先级
            priority = self._determine_priority(description)
            
            # 提取截止时间
            deadline = self._extract_deadline(description, context)
            
            # 提取标签
            tags = self._extract_tags(description)
            
            # 创建任务
            task_data = {
                'name': task_name,
                'description': description,
                'duration_minutes': duration,
                'priority': priority,
                'deadline': deadline,
                'tags': tags
            }
            
            return TaskCreateRequest(**task_data)
            
        except Exception as e:
            print(f"解析任务失败: {description}, 错误: {e}")
            return None
    
    def _extract_task_name(self, description: str) -> str:
        """提取任务名称"""
        # 改进的名称提取逻辑
        # 去除连接词和修饰词，保留核心任务内容
        
        # 去除连接词和修饰词
        connectors = ['需要', '要', '还要', '另外', '并且', '而且', '同时']
        
        cleaned = description
        for connector in connectors:
            cleaned = cleaned.replace(connector, '')
        
        # 去除时间相关词汇
        time_patterns = [
            r'\d+\s*(分钟|小时|天|周|月)',
            r'今天|明天|后天|下周|下个月',
            r'\d+号|\d+月|\d+年'
        ]
        
        for pattern in time_patterns:
            cleaned = re.sub(pattern, '', cleaned)
        
        # 去除优先级词汇
        priority_words = []
        for words in self.priority_keywords.values():
            priority_words.extend(words)
        
        for word in priority_words:
            cleaned = cleaned.replace(word, '')
        
        # 清理标点符号和多余空格
        cleaned = re.sub(r'[，,;；。]', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned.strip())
        
        # 如果清理后为空或太短，返回原描述的前30个字符
        if not cleaned or len(cleaned) < 3:
            return description[:30].strip()
        
        return cleaned
    
    def _extract_duration(self, description: str) -> int:
        """提取预计耗时"""
        # 匹配时间模式
        patterns = [
            r'(\d+)\s*(分钟|minute)',
            r'(\d+)\s*(小时|hour)',
            r'(\d+)\s*小时半',
            r'半小时',
            r'(\d+)\s*天',
            r'(\d+)\s*周'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, description)
            if match:
                if '半小时' in pattern:
                    return 30
                elif '小时半' in pattern:
                    return 90
                elif '天' in pattern:
                    days = int(match.group(1))
                    return days * 480  # 按8小时工作日计算
                elif '周' in pattern:
                    weeks = int(match.group(1))
                    return weeks * 2400  # 按5天*8小时计算
                else:
                    num = int(match.group(1))
                    unit = match.group(2) if match.lastindex > 1 else ''
                    return num * self.time_units.get(unit, 60)  # 默认按小时
        
        # 默认值：根据描述长度估算
        word_count = len(description)
        if word_count < 10:
            return 30  # 简单任务
        elif word_count < 30:
            return 60  # 中等任务
        else:
            return 120  # 复杂任务
    
    def _determine_priority(self, description: str) -> TaskPriority:
        """确定任务优先级"""
        description_lower = description.lower()
        
        for priority, keywords in self.priority_keywords.items():
            for keyword in keywords:
                if keyword in description_lower:
                    return TaskPriority(priority)
        
        # 根据关键词推断
        urgent_words = ['紧急', '马上', '立刻', 'deadline', '截止']
        important_words = ['重要', '关键', '必须', '必要']
        
        has_urgent = any(word in description_lower for word in urgent_words)
        has_important = any(word in description_lower for word in important_words)
        
        if has_urgent and has_important:
            return TaskPriority.URGENT_IMPORTANT
        elif has_important:
            return TaskPriority.IMPORTANT
        elif has_urgent:
            return TaskPriority.URGENT
        else:
            return TaskPriority.NORMAL
    
    def _extract_deadline(self, description: str, context: Optional[Dict]) -> Optional[str]:
        """提取截止时间"""
        # 匹配日期模式
        date_patterns = [
            r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?',
            r'(\d{1,2})[-/月](\d{1,2})[日号]?',
            r'今天',
            r'明天',
            r'后天',
            r'下周',
            r'下个月'
        ]
        
        today = datetime.now()
        
        for pattern in date_patterns:
            match = re.search(pattern, description)
            if match:
                if '今天' in pattern:
                    return today.replace(hour=18, minute=0, second=0).isoformat()  # 今天18:00
                elif '明天' in pattern:
                    tomorrow = today + timedelta(days=1)
                    return tomorrow.replace(hour=18, minute=0, second=0).isoformat()
                elif '后天' in pattern:
                    day_after_tomorrow = today + timedelta(days=2)
                    return day_after_tomorrow.replace(hour=18, minute=0, second=0).isoformat()
                elif '下周' in pattern:
                    next_week = today + timedelta(days=7)
                    return next_week.replace(hour=18, minute=0, second=0).isoformat()
                elif '下个月' in pattern:
                    next_month = today.replace(month=today.month+1) if today.month < 12 else today.replace(year=today.year+1, month=1)
                    return next_month.replace(hour=18, minute=0, second=0).isoformat()
                else:
                    # 解析具体日期
                    groups = match.groups()
                    if len(groups) == 3:  # 完整日期
                        year, month, day = int(groups[0]), int(groups[1]), int(groups[2])
                    else:  # 月日，使用当前年
                        month, day = int(groups[0]), int(groups[1])
                        year = today.year
                    
                    try:
                        deadline_date = datetime(year, month, day, 18, 0, 0)
                        return deadline_date.isoformat()
                    except ValueError:
                        continue
        
        return None
    
    def _extract_tags(self, description: str) -> List[str]:
        """提取任务标签"""
        tags = []
        
        # 常见标签关键词
        tag_categories = {
            '工作': ['工作', '项目', '会议', '报告', '代码'],
            '学习': ['学习', '读书', '课程', '研究', '论文'],
            '生活': ['生活', '购物', '家务', '清洁', '做饭'],
            '健康': ['健康', '运动', '健身', '跑步', '瑜伽'],
            '娱乐': ['娱乐', '电影', '游戏', '音乐', '旅行']
        }
        
        description_lower = description.lower()
        
        for tag, keywords in tag_categories.items():
            if any(keyword in description_lower for keyword in keywords):
                tags.append(tag)
        
        return tags


# 创建工具函数（用于Nanobot集成）
def parse_user_goal(user_input: str, context: dict = None) -> dict:
    """
    解析用户目标为结构化任务（工具函数）
    
    Args:
        user_input: 用户自然语言描述
        context: 上下文信息
        
    Returns:
        {
            "tasks": List[Task],
            "message": str
        }
    """
    parser = TaskParser()
    
    try:
        tasks = parser.parse_natural_language(user_input, context)
        
        return {
            "tasks": [task.to_dict() for task in tasks],
            "message": f"成功解析出 {len(tasks)} 个任务"
        }
        
    except Exception as e:
        return {
            "tasks": [],
            "message": f"解析失败: {str(e)}"
        }


# 测试函数
if __name__ == "__main__":
    # 测试解析器
    test_inputs = [
        "我需要准备下周的学术报告，还要完成代码review，另外要安排健身时间",
        "今天要写论文和做运动",
        "紧急处理客户投诉，重要项目会议安排在明天下午"
    ]
    
    parser = TaskParser()
    
    for i, test_input in enumerate(test_inputs, 1):
        print(f"\n=== 测试 {i} ===")
        print(f"输入: {test_input}")
        
        tasks = parser.parse_natural_language(test_input)
        
        print(f"解析出 {len(tasks)} 个任务:")
        for task in tasks:
            print(f"  - {task.name} (优先级: {task.priority}, 耗时: {task.duration_minutes}分钟)")