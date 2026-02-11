---
name: restart
description: 自重启 nanobot gateway 进程。Triggers: 重启, restart, reboot, 重新启动
---

# Restart

使用 `setsid` 启动独立进程执行重启脚本，脱离当前 nanobot 进程树，确保 kill 后脚本仍能继续运行并拉起新实例。

## 使用方法

```bash
setsid bash /Users/jing1/Developer/github/nanobot/nanobot/skills/restart/scripts/restart.sh &
```

可选参数：
- 参数1：kill 前等待秒数（默认 2）
- 参数2：启动前等待秒数（默认 10）

```bash
setsid bash /Users/jing1/Developer/github/nanobot/nanobot/skills/restart/scripts/restart.sh 2 10 &
```

## 日志

重启日志位于 `~/.nanobot/restart.log`，重启后应检查日志确认是否成功。

## 注意事项

- 执行后当前 session 会中断，新 session 将在新进程中开始
- 如果重启失败，需要用户手动执行 `nanobot gateway`
