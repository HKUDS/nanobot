# Agent架构对比实验技能

## 技能概述

这是一个用于执行Agent架构对比实验的完整技能，基于2×2全因子设计，对比记忆机制（滑动窗口 vs 向量检索）和工具系统（粗粒度 vs 细粒度）的性能差异。

## 核心功能

### 1. 实验设计
- **2×2全因子设计**：记忆机制 × 工具系统
- **测试任务**：3个标准任务（自我介绍、天气查询、简单计算）
- **评估指标**：Token消耗、执行时间、成功率
- **重复次数**：每组2-6次重复，确保统计显著性

### 2. 多会话Token统计
- **独立会话键**：每个实验有唯一的session_key
- **分流日志**：Token使用记录到独立文件
- **精确统计**：基于API usage字段的精确Token计数
- **JSON格式**：结构化日志，便于分析

### 3. 实验执行
- **串行执行**：避免并发干扰，确保数据准确
- **配置隔离**：每个实验独立工作区和ChromaDB collection
- **环境控制**：相同硬件、网络、时间条件
- **数据收集**：自动收集Token、时间、成功率数据

### 4. 数据分析
- **描述统计**：均值、标准差、中位数、极值
- **对比分析**：配置间对比，任务间对比
- **趋势分析**：识别性能趋势和模式
- **异常检测**：识别高Token消耗异常值

## 使用方法

### 基本使用
```bash
# 执行完整实验
nanobot agent_architecture_experiment run

# 查看实验结果
nanobot agent_architecture_experiment report

# 清理实验数据
nanobot agent_architecture_experiment clean
```

### 高级配置
```python
# 自定义实验配置
from nanobot.skills.agent_architecture_experiment import ExperimentRunner

config = {
    "memory_mechanisms": ["sliding_window", "vector_retrieval"],
    "tool_systems": ["coarse_grained", "fine_grained"],
    "tasks": ["self_intro", "weather_query", "simple_calc"],
    "repetitions": 3,
    "output_dir": "./experiment_results"
}

runner = ExperimentRunner(config)
results = runner.run_experiments()
```

### 命令行参数
```bash
# 指定任务类型
nanobot agent_architecture_experiment run --tasks intro,weather,calc

# 指定重复次数
nanobot agent_architecture_experiment run --repetitions 5

# 指定输出目录
nanobot agent_architecture_experiment run --output ./my_results

# 仅执行特定配置
nanobot agent_architecture_experiment run --configs VR_FG,SW_CG
```

## 实验流程

### 阶段1：实验准备
1. **环境检查**：验证ChromaDB、API密钥、依赖包
2. **目录创建**：创建实验目录结构
3. **配置生成**：生成所有实验配置组合
4. **会话键分配**：为每个实验分配唯一session_key

### 阶段2：实验执行
1. **串行执行**：按顺序执行每个实验配置
2. **Token统计**：通过多会话分流记录Token使用
3. **数据记录**：记录执行时间、成功率、错误信息
4. **日志保存**：保存详细执行日志

### 阶段3：数据分析
1. **数据聚合**：聚合所有实验数据
2. **统计分析**：计算均值、标准差、中位数
3. **对比分析**：配置间对比，任务间对比
4. **异常分析**：识别和处理异常值

### 阶段4：报告生成
1. **表格生成**：生成对比表格
2. **图表绘制**：绘制性能对比图表
3. **结论总结**：总结实验结论和建议
4. **报告输出**：生成HTML/PDF/Markdown报告

## 技术实现

### 核心组件
1. **ExperimentRunner**：实验执行器
2. **TokenTracker**：Token统计器
3. **DataAnalyzer**：数据分析器
4. **ReportGenerator**：报告生成器

### 关键代码
```python
class ExperimentRunner:
    def __init__(self, config):
        self.config = config
        self.token_tracker = TokenTracker()
        self.results = []
    
    def run_experiment(self, memory_mech, tool_sys, task, rep):
        # 设置会话键
        session_key = f"{memory_mech}_{tool_sys}_{task}_rep{rep}"
        set_current_session_key(session_key)
        
        # 执行实验
        start_time = time.time()
        result = self._execute_task(task, memory_mech, tool_sys)
        end_time = time.time()
        
        # 收集数据
        token_usage = self.token_tracker.get_usage(session_key)
        execution_time = end_time - start_time
        
        return {
            "session_key": session_key,
            "memory_mechanism": memory_mech,
            "tool_system": tool_sys,
            "task": task,
            "repetition": rep,
            "token_usage": token_usage,
            "execution_time": execution_time,
            "success": result["success"]
        }
```

### 多会话分流实现
```python
def set_current_session_key(key: str):
    """设置当前会话键"""
    _current_session_key.set(key)

def record_token_usage(usage: dict):
    """记录Token使用"""
    session_key = get_current_session_key()
    if session_key:
        log_file = f"session_{session_key}_token_usage.txt"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0)
            }) + "\n")
```

## 实验结果

### 典型结果
基于23次实验的数据分析：

| 配置组合 | 平均Token消耗 | 标准差 | 稳定性 |
|----------|--------------|--------|--------|
| SW_CG | 150,390 | 187,812 | ❌ 不稳定 |
| SW_FG | 55,218 | 40,894 | ⚠️ 中等 |
| VR_CG | 32,316 | 28,997 | ✅ 较稳定 |
| VR_FG | **11,452** | **307** | ✅✅ 极稳定 |

### 关键发现
1. **向量检索比滑动窗口节省78.7% Token消耗**
2. **细粒度工具比粗粒度工具节省63.5% Token消耗**
3. **VR_FG组合比最差配置节省92.4% Token消耗**
4. **天气查询任务对配置最敏感（37.2倍差异）**

## 最佳实践

### 实验设计
1. **控制变量**：保持硬件、网络、时间条件一致
2. **足够重复**：每组至少3次重复，确保统计显著性
3. **任务覆盖**：覆盖简单、中等、复杂任务类型
4. **环境隔离**：为每个实验创建独立工作区

### 数据收集
1. **精确计时**：使用高精度计时器
2. **完整日志**：记录所有执行细节
3. **错误处理**：记录所有错误和异常
4. **数据备份**：定期备份原始数据

### 数据分析
1. **描述统计**：计算均值、标准差、中位数
2. **对比分析**：使用统计检验验证差异显著性
3. **趋势分析**：识别性能趋势和模式
4. **异常处理**：识别和处理异常值

## 故障排除

### 常见问题
1. **Token统计不准确**
   - 检查session_key是否正确设置
   - 验证API usage字段是否包含Token信息
   - 检查日志文件权限

2. **实验执行失败**
   - 检查API密钥是否有效
   - 验证ChromaDB连接
   - 检查网络连接

3. **数据分析错误**
   - 检查数据格式是否正确
   - 验证统计计算方法
   - 检查异常值处理

### 调试方法
```bash
# 检查Token日志
cat session_*.txt | head -20

# 检查实验日志
tail -f experiment.log

# 验证API连接
nanobot agent_architecture_experiment test_api

# 验证ChromaDB
nanobot agent_architecture_experiment test_chromadb
```

## 应用场景

### 1. 架构选择
- 为新项目选择最优Agent架构
- 评估不同记忆机制的性能差异
- 比较不同工具系统的效率

### 2. 成本优化
- 识别高Token消耗的配置
- 优化API使用成本
- 建立成本预测模型

### 3. 性能评估
- 建立Agent性能基准
- 监控性能变化趋势
- 评估优化效果

### 4. 研究验证
- 验证新算法或架构
- 对比不同实现方案
- 发表学术研究成果

## 扩展功能

### 自定义任务
```python
# 添加自定义任务
custom_tasks = [
    {
        "name": "data_analysis",
        "description": "分析CSV数据文件",
        "prompt": "请分析data.csv文件，计算各列统计量",
        "input_files": ["data.csv"]
    },
    {
        "name": "code_generation",
        "description": "生成Python代码",
        "prompt": "请生成一个计算斐波那契数列的函数",
        "expected_output": "def fibonacci(n): ..."
    }
]
```

### 自定义评估指标
```python
# 添加自定义评估指标
custom_metrics = [
    {
        "name": "code_quality",
        "description": "代码质量评分",
        "evaluator": "code_quality_evaluator",
        "weight": 0.3
    },
    {
        "name": "response_relevance",
        "description": "回答相关性",
        "evaluator": "relevance_evaluator",
        "weight": 0.4
    }
]
```

### 分布式执行
```python
# 支持分布式实验
distributed_config = {
    "workers": 4,
    "scheduler": "redis",
    "result_backend": "mongodb",
    "timeout": 3600
}
```

## 版本历史

### v1.0 (2026-03-29)
- 初始版本发布
- 支持2×2全因子设计
- 多会话Token统计
- 基本数据分析功能

### v1.1 (计划中)
- 支持更多任务类型
- 添加执行时间统计
- 增强报告生成功能
- 支持分布式执行

## 贡献指南

### 代码贡献
1. Fork项目仓库
2. 创建功能分支
3. 编写测试用例
4. 提交Pull Request

### 文档贡献
1. 更新使用文档
2. 添加示例代码
3. 翻译文档
4. 修复文档错误

### 问题反馈
1. 创建Issue描述问题
2. 提供复现步骤
3. 附上相关日志
4. 提出改进建议

## 许可证

MIT License

## 致谢

感谢所有参与Agent架构对比实验的贡献者，特别感谢：
- 实验设计者：提供了科学的实验方法
- 代码贡献者：实现了多会话分流功能
- 数据提供者：提供了宝贵的实验数据
- 用户反馈：帮助改进技能功能

---

**技能创建时间**: 2026-03-29 15:58  
**基于实验**: 23次有效实验，1,484,813 tokens总消耗  
**核心价值**: 为Agent系统提供科学的架构选择依据  
**适用场景**: AI Agent开发、性能评估、成本优化、学术研究