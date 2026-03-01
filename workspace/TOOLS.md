# 可用工具

本文档介绍 nanobot 可用的工具。

## 文件操作

### read_file
读取文件内容。
```
read_file(path: str) -> str
```

### write_file
写入文件内容（必要时会创建父目录）。
```
write_file(path: str, content: str) -> str
```

### edit_file
通过替换指定文本编辑文件。
```
edit_file(path: str, old_text: str, new_text: str) -> str
```

### list_dir
列出目录内容。
```
list_dir(path: str) -> str
```

## Shell 执行

### exec
执行一条 Shell 命令并返回输出。
```
exec(command: str, working_dir: str = None) -> str
```

**安全说明：**
- 命令具有可配置超时（默认 60 秒）
- 危险命令会被拦截（如 rm -rf、format、dd、shutdown 等）
- 输出默认截断至 10,000 字符
- 可选 `restrictToWorkspace` 配置用于限制路径

## 通信

### message
向用户发送消息（内部使用）。
```
message(content: str, channel: str = None, chat_id: str = None) -> str
```

## 后台任务

### spawn
启动一个子代理在后台处理任务。
```
spawn(task: str, label: str = None) -> str
```

用于复杂或耗时的任务，子代理会独立完成并在结束后回报结果。

## 定时提醒（Cron）

使用 `exec` 与 `nanobot cron add` 创建定时提醒：

### 设置重复提醒
```bash
# 每天 9 点
nanobot cron add --name "morning" --message "Good morning! ☀️" --cron "0 9 * * *"

# 每 2 小时
nanobot cron add --name "water" --message "Drink water! 💧" --every 7200
```

### 设置一次性提醒
```bash
# 在指定时间（ISO 格式）
nanobot cron add --name "meeting" --message "Meeting starts now!" --at "2025-01-31T15:00:00"
```

### 管理提醒
```bash
nanobot cron list              # 列出所有任务
nanobot cron remove <job_id>   # 移除任务
```

## 心跳任务管理

工作空间中的 `HEARTBEAT.md` 每 30 分钟检查一次。
使用文件操作管理周期性任务：

### 添加心跳任务
```python
# 追加新任务
edit_file(
    path="HEARTBEAT.md",
    old_text="## Example Tasks",
    new_text="- [ ] New periodic task here\n\n## Example Tasks"
)
```

### 移除心跳任务
```python
# 移除指定任务
edit_file(
    path="HEARTBEAT.md",
    old_text="- [ ] Task to remove\n",
    new_text=""
)
```

### 重写全部任务
```python
# 替换整个文件
write_file(
    path="HEARTBEAT.md",
    content="# Heartbeat Tasks\n\n- [ ] Task 1\n- [ ] Task 2\n"
)
```

---

## 添加自定义工具

添加新工具的步骤：
1. 在 `nanobot/agent/tools/` 中创建继承 `Tool` 的类
2. 实现 `name`、`description`、`parameters`、`execute`
3. 在 `AgentLoop._register_default_tools()` 中注册
