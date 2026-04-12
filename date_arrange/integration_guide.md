# Date Arrange 集成指南

本文档介绍如何将 Date Arrange 模块集成到现有的 Nanobot 项目中。

## 1. 安装依赖

首先安装 Date Arrange 的依赖包：

```bash
pip install -r date_arrange/requirements.txt
```

## 2. 注册技能到 Nanobot

在 Nanobot 的配置文件中注册 Date Arrange 的技能：

```python
# 在 nanobot 的配置文件中添加
from date_arrange.skills.planner.task_parser import parse_user_goal
from date_arrange.skills.planner.schedule_creator import create_optimized_schedule

# 注册工具到 ToolRegistry
tool_registry.register_tool(parse_user_goal)
tool_registry.register_tool(create_optimized_schedule)
```

## 3. 在 MEMORY.md 中存储用户偏好

在用户的 MEMORY.md 文件中添加日程规划相关的偏好设置：

```markdown
# 日程规划偏好

## 工作时间段
- 上午: 09:00-12:00
- 下午: 14:00-18:00

## 任务偏好
- 喜欢将复杂任务安排在上午
- 需要午休时间
- 每天最多安排6小时工作

## 提醒设置
- 提前15分钟提醒会议
- 任务完成时发送通知
```

## 4. 前端集成

### 4.1 添加日程规划界面

在前端项目中添加日程规划相关的组件：

```vue
<!-- ScheduleComponent.vue -->
<template>
  <div class="schedule-container">
    <h3>日程规划</h3>
    <div class="input-section">
      <textarea v-model="userInput" placeholder="请输入您的日程安排需求..."></textarea>
      <button @click="parseSchedule">解析任务</button>
    </div>
    
    <div v-if="tasks.length > 0" class="tasks-section">
      <h4>解析出的任务</h4>
      <ul>
        <li v-for="task in tasks" :key="task.id">
          {{ task.name }} ({{ task.duration_minutes }}分钟, {{ task.priority }})
        </li>
      </ul>
      <button @click="createSchedule">创建日程</button>
    </div>
    
    <div v-if="schedule" class="schedule-section">
      <h4>优化日程</h4>
      <div class="schedule-details">
        <p>日期: {{ schedule.date }}</p>
        <p>总耗时: {{ schedule.total_duration }}分钟</p>
        <p>效率评分: {{ schedule.efficiency_score }}</p>
      </div>
    </div>
  </div>
</template>

<script>
export default {
  data() {
    return {
      userInput: '',
      tasks: [],
      schedule: null
    }
  },
  methods: {
    async parseSchedule() {
      const response = await this.$api.post('/schedule/parse', {
        user_input: this.userInput
      })
      this.tasks = response.data.tasks
    },
    
    async createSchedule() {
      const response = await this.$api.post('/schedule/create', {
        tasks: this.tasks,
        date: new Date().toISOString().split('T')[0]
      })
      this.schedule = response.data.schedule
    }
  }
}
</script>
```

### 4.2 API 调用示例

```javascript
// 解析用户输入
const parseResponse = await fetch('/schedule/parse', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    user_input: '需要准备下周的学术报告和代码review'
  })
})

// 创建日程
const createResponse = await fetch('/schedule/create', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    tasks: parsedTasks,
    date: '2024-04-08',
    constraints: {
      available_time: 480,
      work_hours: [['09:00', '12:00'], ['14:00', '18:00']]
    }
  })
})
```

## 5. 技能调用示例

### 5.1 在 Nanobot 对话中使用

用户可以直接通过自然语言与 Nanobot 交互来使用日程规划功能：

```
用户: 帮我安排一下下周的工作日程

Nanobot: 好的，请告诉我您下周需要完成哪些任务？

用户: 需要准备学术报告、完成代码review、安排团队会议、还要健身

Nanobot: 已为您解析出4个任务，正在创建优化日程...
         - 准备学术报告 (180分钟, 重要)
         - 代码review (60分钟, 重要) 
         - 团队会议 (90分钟, 普通)
         - 健身 (60分钟, 普通)
         
         已为您创建优化日程，效率评分0.85，建议...
```

### 5.2 技能工具调用

在 Nanobot 技能中直接调用 Date Arrange 功能：

```python
from date_arrange.skills.planner.task_parser import parse_user_goal
from date_arrange.skills.planner.schedule_creator import create_optimized_schedule

async def schedule_planning_skill(user_input: str, context: dict):
    """日程规划技能"""
    
    # 解析用户输入
    parse_result = parse_user_goal(user_input, context)
    
    if not parse_result["tasks"]:
        return "抱歉，我没有理解您的日程安排需求"
    
    # 创建日程
    schedule_result = create_optimized_schedule(
        parse_result["tasks"], 
        context.get("date", "2024-04-08"),
        context.get("constraints", {})
    )
    
    # 构建响应
    response = f"已为您创建优化日程：\n"
    response += f"- 日期: {schedule_result['schedule']['date']}\n"
    response += f"- 总耗时: {schedule_result['schedule']['total_duration']}分钟\n"
    response += f"- 效率评分: {schedule_result['schedule']['efficiency_score']}\n"
    
    if schedule_result['suggestions']:
        response += "\n改进建议:\n"
        for suggestion in schedule_result['suggestions']:
            response += f"- {suggestion}\n"
    
    return response
```

## 6. 配置选项

### 6.1 默认配置

Date Arrange 提供以下默认配置选项：

```python
# 在配置文件中设置
DATE_ARRANGE_CONFIG = {
    'default_work_hours': [
        ('09:00', '12:00'),
        ('14:00', '18:00')
    ],
    'default_available_time': 480,  # 8小时
    'time_slot_duration': 45,       # 45分钟工作块
    'break_duration': 5,             # 5分钟休息
    'max_tasks_per_day': 10         # 每天最多任务数
}
```

### 6.2 个性化配置

支持从用户 MEMORY.md 中读取个性化配置：

```python
def load_user_preferences(memory_content: str) -> dict:
    """从 MEMORY.md 加载用户偏好"""
    preferences = {}
    
    # 解析工作时间段
    work_hours_match = re.search(r'工作时间段[\s\S]*?上午:\s*(\d+:\d+)-(\d+:\d+)', memory_content)
    if work_hours_match:
        preferences['work_hours'] = [
            (work_hours_match.group(1), work_hours_match.group(2))
        ]
    
    return preferences
```

## 7. 测试集成

### 7.1 单元测试

运行 Date Arrange 的单元测试：

```bash
cd date_arrange
python -m pytest tests/ -v
```

### 7.2 集成测试

测试与 Nanobot 的集成：

```python
# test_integration.py
import pytest
from date_arrange.skills.planner.task_parser import parse_user_goal

class TestIntegration:
    def test_parse_with_nanobot_context(self):
        """测试在 Nanobot 上下文中的解析"""
        context = {
            'user_id': 'test_user',
            'conversation_id': 'test_conv',
            'date': '2024-04-08'
        }
        
        result = parse_user_goal('需要安排工作日程', context)
        assert 'tasks' in result
        assert 'message' in result
```

## 8. 部署注意事项

### 8.1 依赖管理

确保所有依赖包版本兼容：

```txt
# requirements.txt
fastapi>=0.104.0
pydantic>=2.0.0
uvicorn>=0.24.0
```

### 8.2 性能优化

对于生产环境，建议：
- 使用数据库存储任务和日程数据
- 实现缓存机制
- 添加异步任务处理
- 设置合理的超时时间

### 8.3 安全考虑

- 验证用户输入
- 限制任务数量和时间范围
- 实现访问控制
- 记录操作日志

## 9. 故障排除

### 9.1 常见问题

**问题**: 任务解析失败
**解决**: 检查输入格式，确保包含明确的任务描述

**问题**: 日程创建超时
**解决**: 增加可用时间或减少任务数量

**问题**: 集成后 Nanobot 无法启动
**解决**: 检查依赖包版本兼容性

### 9.2 日志调试

启用详细日志记录：

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 10. 扩展开发

Date Arrange 设计为可扩展的模块，支持以下扩展：

- 添加新的任务解析规则
- 实现自定义优化算法
- 集成第三方日历服务
- 添加机器学习预测功能

如需扩展开发，请参考源码中的接口定义和示例实现。