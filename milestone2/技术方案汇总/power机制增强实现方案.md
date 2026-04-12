# Power 机制增强实现方案

## 📊 方案概述

基于现有技术方案，增强日志记录和文件监控功能，提供完整的可观测性支持。

## 🔧 增强功能设计

### 1. 详细日志记录系统

#### 1.1 日志级别定义
```python
LOG_LEVELS = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50
}
```

#### 1.2 结构化日志格式
```python
class PowerLogger:
    def __init__(self, log_file="power_logs.jsonl"):
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(exist_ok=True)
        
    def log(self, level, conversation_id, action, details, file_changes=None):
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "conversation_id": conversation_id,
            "action": action,
            "details": details,
            "file_changes": file_changes or {},
            "memory_usage": self._get_memory_usage(),
            "system_info": self._get_system_info()
        }
        
        # 写入JSONL文件
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        
        # 控制台输出
        print(f"[{level}] {conversation_id} - {action}: {details}")
```

### 2. 文件大小变化监控

#### 2.1 文件监控器
```python
class FileMonitor:
    def __init__(self):
        self.file_snapshots = {}
        
    def take_snapshot(self, file_path):
        """记录文件当前状态"""
        path = Path(file_path)
        if path.exists():
            snapshot = {
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
                "lines": self._count_lines(path)
            }
            self.file_snapshots[str(path)] = snapshot
            return snapshot
        return None
        
    def check_changes(self, file_path):
        """检查文件变化"""
        path = Path(file_path)
        if str(path) not in self.file_snapshots:
            return {"status": "no_previous_snapshot"}
            
        old_snapshot = self.file_snapshots[str(path)]
        if not path.exists():
            return {"status": "file_deleted"}
            
        new_snapshot = self.take_snapshot(file_path)
        
        changes = {
            "status": "changed",
            "size_delta": new_snapshot["size"] - old_snapshot["size"],
            "size_percent": ((new_snapshot["size"] - old_snapshot["size"]) / old_snapshot["size"]) * 100 if old_snapshot["size"] > 0 else 0,
            "lines_delta": new_snapshot["lines"] - old_snapshot["lines"],
            "old_size": old_snapshot["size"],
            "new_size": new_snapshot["size"],
            "old_lines": old_snapshot["lines"],
            "new_lines": new_snapshot["lines"]
        }
        
        return changes
```

### 3. 增强的Power计算引擎

#### 3.1 带日志的Power计算器
```python
class EnhancedPowerCalculator(PowerCalculator):
    def __init__(self, alpha=0.6, beta=0.4, gamma=0.9, logger=None):
        super().__init__(alpha, beta, gamma)
        self.logger = logger or PowerLogger()
        self.file_monitor = FileMonitor()
        
    def update_power_with_logging(self, conversation_id, old_power, delta, reason, files_to_monitor=None):
        """带详细日志的Power更新"""
        
        # 记录更新前的文件状态
        file_changes = {}
        if files_to_monitor:
            for file_path in files_to_monitor:
                self.file_monitor.take_snapshot(file_path)
        
        # 计算新Power值
        new_power = self.update_power(old_power, delta)
        
        # 记录文件变化
        if files_to_monitor:
            for file_path in files_to_monitor:
                changes = self.file_monitor.check_changes(file_path)
                if changes["status"] == "changed":
                    file_changes[str(file_path)] = changes
        
        # 记录详细日志
        log_details = {
            "old_power": old_power,
            "new_power": new_power,
            "delta": delta,
            "reason": reason,
            "parameters": {
                "alpha": self.alpha,
                "beta": self.beta,
                "gamma": self.gamma
            }
        }
        
        self.logger.log(
            "INFO", 
            conversation_id, 
            "power_update", 
            log_details,
            file_changes
        )
        
        return new_power
```

## 🚀 完整实现代码

### 1. 增强的BFF服务扩展

```python
# 在 bff_service.py 中添加

class EnhancedPowerManager:
    def __init__(self):
        self.calculator = EnhancedPowerCalculator()
        self.monitored_files = [
            "trajectory.jsonl",
            "memory/MEMORY.md", 
            "conversation_history.json"
        ]
    
    async def update_power_auto(self, conversation_id: str, reward: float):
        """自动更新Power（带详细日志）"""
        async with conversations_lock:
            conv = conversations.get(conversation_id)
            if not conv:
                self.calculator.logger.log("WARNING", conversation_id, "power_update", "Conversation not found")
                return
                
            old_power = conv["power"]
            delta = self.calculator.calculate_delta(reward_norm=reward)
            
            # 构建文件监控路径
            files_to_monitor = []
            for rel_path in self.monitored_files:
                # 获取容器内的文件路径
                container_path = f"/app/workspace/conv_{conversation_id}/{rel_path}"
                files_to_monitor.append(container_path)
            
            new_power = self.calculator.update_power_with_logging(
                conversation_id, old_power, delta, 
                f"auto_reward_{reward}", files_to_monitor
            )
            
            conv["power"] = new_power
            conv.setdefault("power_history", []).append({
                "timestamp": datetime.now(TZ_UTC8).isoformat(),
                "value": new_power,
                "reason": f"auto_reward_{reward}",
                "file_changes": self.calculator.file_monitor.file_snapshots
            })
            
            # 限制历史记录长度
            if len(conv["power_history"]) > 100:
                conv["power_history"] = conv["power_history"][-100:]
    
    async def update_power_by_annotation(self, conversation_id: str, label: str, is_add: bool):
        """标注更新Power（带详细日志）"""
        score = LABEL_SCORES.get(label, 0)
        if not is_add:
            score = -score
            
        async with conversations_lock:
            conv = conversations.get(conversation_id)
            if not conv:
                return
                
            old_power = conv["power"]
            delta = self.calculator.calculate_delta(reward_norm=0.5, annotation_score=score)
            
            new_power = self.calculator.update_power_with_logging(
                conversation_id, old_power, delta,
                f"annotation_{label}_{'add' if is_add else 'remove'}",
                self.monitored_files
            )
            
            conv["power"] = new_power
            conv["power_history"].append({
                "timestamp": datetime.now(TZ_UTC8).isoformat(),
                "value": new_power,
                "reason": f"annotation_{label}_{'add' if is_add else 'remove'}"
            })

# 全局实例
power_manager = EnhancedPowerManager()
```

### 2. 增强的API接口

```python
@app.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
async def send_message(conversation_id: str, req: MessageSend):
    """发送消息并自动更新Power"""
    # ... 原有逻辑 ...
    
    result = resp.json()
    
    # 提取reward并更新Power
    trajectory = result.get("trajectory", [])
    if trajectory:
        last_r = trajectory[-1].get("r_t", 0.5)
        await power_manager.update_power_auto(conversation_id, last_r)
    
    return MessageResponse(**result)

@app.get("/conversations/{conversation_id}/power/logs")
async def get_power_logs(conversation_id: str, limit: int = 50):
    """获取Power更新日志"""
    conv = conversations.get(conversation_id)
    if not conv:
        raise HTTPException(404)
    
    # 读取日志文件
    log_file = Path("power_logs.jsonl")
    if not log_file.exists():
        return {"logs": []}
    
    logs = []
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                log_entry = json.loads(line)
                if log_entry.get("conversation_id") == conversation_id:
                    logs.append(log_entry)
    
    return {"logs": logs[-limit:]}

@app.get("/conversations/{conversation_id}/power/files")
async def get_power_file_stats(conversation_id: str):
    """获取相关文件统计信息"""
    stats = {}
    
    for rel_path in power_manager.monitored_files:
        file_path = Path(f"/app/workspace/conv_{conversation_id}/{rel_path}")
        if file_path.exists():
            stats[rel_path] = {
                "size": file_path.stat().st_size,
                "lines": sum(1 for _ in open(file_path, "r", encoding="utf-8")),
                "exists": True
            }
        else:
            stats[rel_path] = {"exists": False}
    
    return {"file_stats": stats}
```

### 3. 前端监控面板

```vue
<template>
  <div class="power-monitor">
    <div class="power-stats">
      <h3>Power 监控面板</h3>
      <div class="current-power">
        <span class="power-value" :class="powerClass(currentPower)">
          {{ Math.round(currentPower) }}
        </span>
        <span class="power-level">{{ powerLevel(currentPower) }}</span>
      </div>
    </div>
    
    <div class="file-monitor">
      <h4>文件监控</h4>
      <div v-for="(stat, filename) in fileStats" :key="filename" class="file-stat">
        <span class="filename">{{ filename }}</span>
        <span v-if="stat.exists" class="file-info">
          {{ stat.size }} bytes, {{ stat.lines }} lines
        </span>
        <span v-else class="file-missing">文件不存在</span>
      </div>
    </div>
    
    <div class="power-history">
      <h4>Power 历史</h4>
      <div v-for="entry in powerHistory" :key="entry.timestamp" class="history-entry">
        <span class="timestamp">{{ formatTime(entry.timestamp) }}</span>
        <span class="value" :class="powerClass(entry.value)">{{ entry.value }}</span>
        <span class="reason">{{ entry.reason }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useConversationStore } from '../stores/conversation'

const currentPower = ref(50)
const fileStats = ref({})
const powerHistory = ref([])

const fetchPowerData = async () => {
  const convId = useConversationStore().currentConversationId
  if (!convId) return
  
  // 获取Power信息
  const powerResp = await fetch(`/conversations/${convId}/power`)
  const powerData = await powerResp.json()
  currentPower.value = powerData.power
  powerHistory.value = powerData.history
  
  // 获取文件统计
  const statsResp = await fetch(`/conversations/${convId}/power/files`)
  const statsData = await statsResp.json()
  fileStats.value = statsData.file_stats
}

// 每30秒更新一次
onMounted(() => {
  fetchPowerData()
  setInterval(fetchPowerData, 30000)
})
</script>
```

## 📊 日志分析工具

### 1. 日志分析脚本
```python
import json
from collections import defaultdict
from datetime import datetime

class PowerLogAnalyzer:
    def __init__(self, log_file="power_logs.jsonl"):
        self.log_file = Path(log_file)
    
    def analyze_conversation(self, conversation_id):
        """分析特定对话的Power变化"""
        logs = self._load_logs_for_conversation(conversation_id)
        
        analysis = {
            "total_updates": len(logs),
            "power_range": self._get_power_range(logs),
            "update_frequency": self._get_update_frequency(logs),
            "file_change_stats": self._analyze_file_changes(logs),
            "reasons_breakdown": self._analyze_update_reasons(logs)
        }
        
        return analysis
    
    def _load_logs_for_conversation(self, conversation_id):
        logs = []
        if self.log_file.exists():
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        log = json.loads(line)
                        if log.get("conversation_id") == conversation_id:
                            logs.append(log)
        return logs
```

## 🎯 实施计划

### 阶段1: 基础日志系统 (0.5天)
- 实现PowerLogger和FileMonitor
- 集成到现有Power计算器

### 阶段2: 增强API接口 (0.5天) 
- 添加日志查询和文件监控API
- 更新现有接口添加日志记录

### 阶段3: 前端监控面板 (1天)
- 实现Power监控界面
- 添加文件状态显示

### 阶段4: 分析工具 (0.5天)
- 实现日志分析脚本
- 添加性能监控

## 💡 优势

1. **完整可观测性**: 每个Power更新都有详细日志
2. **文件变化监控**: 实时跟踪相关文件大小变化
3. **性能分析**: 提供Power变化趋势分析
4. **调试友好**: 详细的错误和状态信息
5. **生产就绪**: 支持大规模部署的监控需求

这个增强方案将确保Power机制的实现具有完整的可观测性和调试能力！