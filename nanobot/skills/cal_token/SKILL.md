# cal_token 技能文档（v3.0 —— 多会话分流版）

## 1. 技能名称
**cal_token** —— DeepSeek API Token 消耗统计（多会话分流 + 求和法）

## 2. 适用范围
- 调用 DeepSeek API（或其他返回单次请求 `total_tokens` 的 API）
- **需要同时或先后运行多个独立任务（会话）**，且希望分别统计每个会话的 token 消耗
- 用于成本核算、性能分析或调试

## 3. 核心原理
- 每个任务（会话）使用**独立的会话 ID**，并在 API 调用时通过**监听机制**将返回的 `usage` 信息写入**该会话专属的日志文件**。
- 统计时，对每个会话的日志文件**独立求和**（同 v2.0 求和法），得出该会话的总 token 消耗。

## 4. 前提条件
- 每次调用 DeepSeek API 后，能够获取到 `usage` 对象。
- 能够维护当前会话的 ID（例如在代码中设置一个全局变量或通过上下文管理）。
- 日志文件存放目录存在且有写入权限。

---

## 5. 操作步骤

### 5.1 会话初始化
在开始一个新任务之前：
1. 生成一个**唯一的会话 ID**（例如 `session_20260329_133000`，或使用 UUID）。
2. 确定该会话的专属日志文件路径，例如：
   ```
   D:\collections2026\phd_application\nanobot1\personal\logs\session_<ID>_token_usage.txt
   ```
3. 记录会话开始时间（精确到秒，便于后续校验）。

### 5.2 执行任务并监听 usage
在每次 API 调用完成后，立即执行以下操作：
1. 获取本次调用的 `usage` 对象（包含 `prompt_tokens`、`completion_tokens`、`total_tokens`）。
2. 将当前时间戳（精确到秒）与 `usage` 数据一起，**以 JSON 或 CSV 格式追加写入当前会话的日志文件**。
3. **注意**：如果同一代码中同时运行多个会话，必须确保 usage 被正确写入对应会话的日志，而不是混淆。

### 5.3 会话结束
任务完成时：
1. 记录会话结束时间（精确到秒）。
2. **不需要对日志文件做任何特殊标记**，因为所有该会话的 usage 已经按顺序写入。

### 5.4 统计 Token 消耗
对于每个会话：
1. 读取其专属日志文件。
2. 对文件中的所有记录，分别计算：
   - `总 prompt_tokens` = 所有 `prompt_tokens` 之和
   - `总 completion_tokens` = 所有 `completion_tokens` 之和
   - `总 total_tokens` = 所有 `total_tokens` 之和
3. 输出统计结果，并可选择计算费用。

---

## 6. 分流实现示例（Python）

以下示例展示如何在代码中实现会话管理及 usage 分流记录。

```python
import json
import uuid
from datetime import datetime
from pathlib import Path

class SessionLogger:
    def __init__(self, base_dir="D:/collections2026/phd_application/nanobot1/personal/logs"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.current_session_id = None
        self.current_log_file = None

    def start_session(self, session_id=None):
        """开始一个新会话，生成日志文件"""
        if session_id is None:
            session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.current_session_id = session_id
        log_filename = f"{session_id}_token_usage.txt"
        self.current_log_file = self.base_dir / log_filename
        # 可选：写入会话开始标记（便于调试）
        with open(self.current_log_file, "a", encoding="utf-8") as f:
            f.write(f"# Session start: {datetime.now().isoformat()}\n")
        return session_id

    def log_usage(self, usage):
        """记录本次API调用的usage到当前会话日志"""
        if self.current_log_file is None:
            raise RuntimeError("No active session. Call start_session() first.")
        record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0)
        }
        with open(self.current_log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def end_session(self):
        """结束当前会话（可选，仅用于记录）"""
        if self.current_log_file:
            with open(self.current_log_file, "a", encoding="utf-8") as f:
                f.write(f"# Session end: {datetime.now().isoformat()}\n")
        self.current_session_id = None
        self.current_log_file = None

# 使用示例
logger = SessionLogger()

# 任务A
logger.start_session("task_A")
response = deepseek_api_call(...)   # 假设返回包含usage
logger.log_usage(response["usage"])
# ... 多次调用 ...
logger.end_session()

# 任务B
logger.start_session("task_B")
response2 = deepseek_api_call(...)
logger.log_usage(response2["usage"])
logger.end_session()
```

**关键点**：
- 每次调用 `log_usage` 前必须保证已调用 `start_session`，且未调用 `end_session`。
- 每个会话的日志文件独立，统计时分别处理。

---

## 7. 统计与计算

### 7.1 对单个会话求和（Python 示例）
```python
def calculate_session_total(log_file_path):
    total_prompt = 0
    total_completion = 0
    total_all = 0
    count = 0
    with open(log_file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                record = json.loads(line)
                total_prompt += record["prompt_tokens"]
                total_completion += record["completion_tokens"]
                total_all += record["total_tokens"]
                count += 1
            except:
                print(f"跳过无效行: {line}")
    return {
        "requests": count,
        "prompt_tokens": total_prompt,
        "completion_tokens": total_completion,
        "total_tokens": total_all
    }
```

### 7.2 输出格式示例
```
会话ID: task_A
请求次数: 12
总输入 Token (prompt): 152,340
总输出 Token (completion): 8,246
总 Token (total): 160,586
预估费用: $0.xx
```

---

## 8. 注意事项

1. **会话隔离**：务必确保不同任务使用不同的 `session_id`，避免 usage 混写到一个文件中。
2. **日志目录管理**：建议按日期或任务类型创建子目录，便于归档。
3. **时间精确性**：记录的时间戳用于调试和核查，但求和法不依赖时间顺序。
4. **异常处理**：如果 API 调用失败，不应记录 usage（或记录空值，但最好明确标记）。
5. **文件写入性能**：每次调用都追加写入，对于高频调用可能会影响性能，可考虑缓冲写入（如使用队列异步写入），但一般场景下直接追加足够。
6. **多线程/异步**：如果代码涉及多线程或异步，需要确保每个会话的日志写入操作是线程安全的（可使用锁或每个线程独立的 logger 实例）。

---

## 9. 版本记录
| 版本 | 日期 | 说明 |
|------|------|------|
| 3.0 | 2026-03-29 | 增加多会话分流机制，支持独立日志文件 |
| 2.0 | 2026-03-29 | 从差值法改为求和法，适配 DeepSeek API |
| 1.0 | 2025-xx-xx | 初始版本（差值法，已废弃） |

---

## 10. 常见问题

**Q1：我已经有一个全局的 token 日志文件，如何迁移到多会话模式？**  
A1：可以编写脚本，根据日志中的时间戳和任务边界将记录拆分到不同会话文件中。但更推荐从新任务开始使用新方案。

**Q2：一个会话可能会跨多天，日志文件会不会太大？**  
A2：可以按天或按大小滚动文件，但求和时需读取所有部分。建议会话结束即归档，避免单个文件过大。

**Q3：如何自动区分不同任务（例如同一代码多次运行）？**  
A3：在每次运行前，通过环境变量、配置文件或命令行参数传入 `session_id`，或者自动生成带时间戳的 ID。

**Q4：我需要同时运行多个任务（并发），如何保证日志不冲突？**  
A4：每个任务实例使用自己的 `SessionLogger` 对象，且写入不同的文件，天然隔离。如果多个线程共享同一个 logger，请确保线程安全（例如为每个线程创建独立 logger 或加锁）。

---

## 11. 总结

本技能文档 v3.0 在 v2.0（求和法）基础上，增加了**多会话分流**能力，使你能够清晰分离不同任务的 token 消耗，避免上下文混淆，为成本核算提供更精确的数据。