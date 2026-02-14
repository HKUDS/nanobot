# 服务器持续运行问题修复

## 问题诊断

程序在服务器上无法持续运行的根本原因有两个：

### 1. Channel Manager 的致命缺陷 (`channels/manager.py:86`)

**原始代码：**
```python
await asyncio.gather(*tasks, return_exceptions=True)
```

**问题：**
- `return_exceptions=True` 会捕获所有异常但不传播
- 当任何一个 channel 的 `start()` 方法返回或抛出异常时，`start_all()` 会静默完成并返回
- 一旦 `start_all()` 返回，主程序就会退出

### 2. Telegram Channel 的无条件退出 (`telegram.py:195`)

**原始代码：**
```python
await self._app.updater.start_polling(...)

# If we get here, polling was stopped normally
break
```

**问题：**
- 当 polling 因任何原因停止时（网络波动、Telegram 服务器重启等），会执行 `break`
- 这导致 `start()` 方法返回，触发上述 Channel Manager 的问题
- 程序看起来"正常"退出，但实际上是意外停止

## 修复方案

### 1. Channel Manager 自动重启机制

**修改文件：** `nanobot/channels/manager.py`

**改进：**
- 移除 `return_exceptions=True`
- 为每个 channel 添加独立的自动重启包装器 `_run_channel_with_restart()`
- 实现指数退避策略（2^n 秒，最大 5 分钟）
- 持续监控和重启失败的 channel

**关键代码：**
```python
async def _run_channel_with_restart(self, name: str, channel: BaseChannel) -> None:
    """Run a channel with automatic restart on failure."""
    consecutive_failures = 0
    max_consecutive_failures = 10

    while True:
        try:
            logger.info(f"Starting {name} channel...")
            await channel.start()

            # If start() returns normally, log and restart
            logger.warning(f"{name} channel stopped unexpectedly, restarting...")
            consecutive_failures += 1

        except asyncio.CancelledError:
            logger.info(f"{name} channel cancelled")
            raise

        except Exception as e:
            consecutive_failures += 1
            logger.error(f"{name} channel error: {e}")

        # Exponential backoff
        wait_time = min(2 ** min(consecutive_failures, 8), 300)
        logger.info(f"Restarting {name} channel in {wait_time}s...")
        await asyncio.sleep(wait_time)
```

### 2. Telegram Channel 智能重启

**修改文件：** `nanobot/channels/telegram.py`

**改进：**
- 区分用户主动停止和意外停止
- 只在用户请求时才退出循环
- 意外停止时自动重试

**关键代码：**
```python
await self._app.updater.start_polling(...)

# If we get here, polling was stopped
if not self._running:
    # User requested shutdown
    logger.info("Telegram polling stopped by user request")
    break
else:
    # Unexpected stop, will retry
    logger.warning("Telegram polling stopped unexpectedly, will retry...")
    await asyncio.sleep(5)
```

## 修复效果

### 修复前
- ❌ Channel 意外停止导致整个程序退出
- ❌ 无法自动恢复
- ❌ 需要手动重启服务
- ❌ 日志不清晰，难以诊断

### 修复后
- ✅ Channel 停止时自动重启
- ✅ 指数退避避免频繁重试
- ✅ 每个 channel 独立运行，互不影响
- ✅ 详细的日志记录重启过程
- ✅ 程序可以 24/7 持续运行

## 部署说明

1. **更新代码：**
   ```bash
   git pull
   ```

2. **重启服务：**
   ```bash
   # 如果使用 systemd
   sudo systemctl restart nanobot

   # 如果使用 screen/tmux
   pkill -f nanobot
   nanobot serve
   ```

3. **监控日志：**
   ```bash
   # 查看重启记录
   grep "Restarting.*channel" /path/to/logs

   # 查看 channel 状态
   grep "channel.*active\|connected" /path/to/logs
   ```

## 预期行为

现在程序会：
1. 自动检测 channel 停止
2. 记录详细的错误信息
3. 使用指数退避自动重启
4. 持续运行直到用户主动停止

## 故障排除

如果仍然遇到问题：

1. **检查日志中的错误模式：**
   ```bash
   tail -f /path/to/logs | grep -E "error|failed|stopped"
   ```

2. **验证配置：**
   ```bash
   nanobot status
   ```

3. **检查网络连接：**
   - Telegram: 确保可以访问 api.telegram.org
   - WhatsApp: 确保 bridge 服务正常运行

4. **查看重启频率：**
   - 如果重启间隔持续增长到 5 分钟，说明存在持续性问题
   - 检查 API token、网络配置等

## 技术细节

### 修改的文件
1. `nanobot/channels/manager.py` - 添加自动重启机制
2. `nanobot/channels/telegram.py` - 修复无条件退出问题

### 新增功能
- 每个 channel 独立的重启循环
- 指数退避算法（2^n 秒，最大 300 秒）
- 连续失败计数和日志
- 区分正常停止和异常停止

### 兼容性
- 不影响现有配置
- 向后兼容
- 不需要修改用户代码
