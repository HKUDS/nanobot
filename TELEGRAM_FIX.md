# Telegram 机器人连接问题修复说明

## 问题描述

Telegram 机器人经常隔一段时间就无法回复消息，尽管看起来仍在运行。错误日志显示：

```
telegram.error.Conflict: Conflict: terminated by other getUpdates request; 
make sure that only one bot instance is running
```

## 根本原因

原始代码存在以下问题：

1. **无法监控 Polling 状态**：当 `start_polling()` 启动后，代码进入一个空的 `while` 循环，无法检测 polling 任务是否实际仍在运行。

2. **不完整的异常处理**：只捕获 `Conflict` 异常，其他导致 polling 停止的异常（网络错误、超时等）会导致代码进入无限循环而无法恢复。

3. **无重试机制**：当 polling 失败时，代码立即返回而不是尝试重新连接。

4. **缺乏诊断信息**：错误信息不足以帮助用户快速定位问题。

## 解决方案

### 1. 轮询任务监控
```python
self._polling_task = asyncio.create_task(
    self._app.updater.start_polling(...)
)
```
- 将 polling 作为一个独立的任务运行
- 定期检查任务是否仍在运行

### 2. 自动恢复机制
- 实现最多 5 次的重试机制
- 使用指数退避策略（1s, 2s, 4s, 8s, 16s）
- 每次重试都创建全新的 Application 实例

### 3. 增强的异常处理
```python
# 捕获所有异常，不仅仅是 Conflict
try:
    # polling 逻辑
except Conflict as e:
    # 处理冲突（另一个实例运行）
except Exception as e:
    # 处理其他错误（网络、超时等）
```

### 4. 更好的诊断信息
当 max retries 达到时，给出具体的故障排除建议：
```
1. Kill other bot processes: pkill -f 'python.*nanobot'
2. Check Docker: docker ps | grep telegram
3. Disable webhook: curl https://api.telegram.org/bot{token}/deleteWebhook
```

## 使用前后对比

### 之前
- ❌ 机器人停止响应但仍显示运行
- ❌ 无法自动恢复
- ❌ 日志信息不清楚

### 之后  
- ✅ 自动检测 polling 失败
- ✅ 最多重试 5 次自动恢复
- ✅ 详细的日志和故障排除建议

## 部署说明

无需任何额外配置。更新代码后自动生效。

## 监控日志

查看是否成功恢复：
```bash
# 查看成功的连接
grep "Telegram polling started successfully" /path/to/logs

# 查看重试记录
grep "Retrying" /path/to/logs

# 查看失败的记录
grep "Max retries reached" /path/to/logs
```

## 故障排除

如果仍然出现 `Conflict` 错误：

### 1. 检查是否有多个 bot 进程
```bash
ps aux | grep -E "nanobot|telegram" | grep -v grep
```

### 2. 杀死所有相关进程
```bash
pkill -f "python.*nanobot"
# 或
pkill -f "telegram"
```

### 3. 如果使用 Docker
```bash
docker ps | grep -i telegram
docker kill <container_id>
```

### 4. 清除 Telegram Webhook（如果之前配置过）
```bash
curl "https://api.telegram.org/bot<YOUR_TOKEN>/deleteWebhook"
```

## 技术细节

### 新增字段
- `_polling_task`: 跟踪 polling 任务
- `_polling_started`: 标记 polling 是否成功启动

### 修改的方法
- `start()`: 完整工作流重写，支持重试和监控
- `stop()`: 增强清理逻辑，包括任务取消和超时
- `send()`: 增强状态检查和错误处理

### 改进的异常处理
- 分别处理 `Conflict` 和其他异常
- 指数退避重试算法
- 完整的清理和资源释放

## 预期效果

通过这个修复，您应该会看到：
1. 机器人更稳定地保持连接
2. 如果连接中断，自动恢复而不需要手动重启
3. 更清楚的日志帮助诊断问题
4. "经常隔一段时间就不回消息"的问题大幅改善
