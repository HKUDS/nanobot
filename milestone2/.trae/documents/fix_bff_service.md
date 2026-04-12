# BFF Service 修复计划

## 问题清单

| 优先级 | 问题 | 修复措施 |
|--------|------|----------|
| 🔴 高 | 结算评级未实现 | close_bounty 已有完整流程，确认调用正确 |
| 🔴 高 | 全局状态无持久化 | 添加 conversations 表，启动时恢复 |
| 🔴 高 | 接口路径不匹配 | curate 接口路径匹配，无需修改 |
| 🟡 中 | 邻居全连接改为仅父子 | 修改定时任务，只处理 fork 关系 |
| 🟡 中 | 容器健康监控缺失 | 已有 startup 清理，需增强 |
| 🟡 中 | 硬编码 API Key | 移除 bff_service.py:1166 的默认值 |
| 🟢 低 | 日志系统统一 | 暂时保留 print，后续优化 |

---

## 修复任务

### Task 1: 确认 close_bounty 流程
- [ ] 确认 close_bounty 正确调用了 evaluate_and_reward
- [ ] 检查接口是否存在

### Task 2: 添加全局状态持久化
- [ ] 创建 conversations_backup 表
- [ ] 启动时从数据库恢复 conversations
- [ ] 对话变更时同步到数据库

### Task 3: 修改邻居发现逻辑
- [ ] 改为只处理 fork 产生的父子关系
- [ ] 或者只自动连接 fork 前后创建的关系

### Task 4: 移除硬编码 API Key
- [ ] bff_service.py:1166 移除默认值

### Task 5: 增强容器健康监控
- [ ] 添加定期探活任务
- [ ] 记录容器健康状态

---

## 修复文件清单

| 文件 | 修改内容 |
|------|----------|
| `bff/db.py` | 添加 conversations_backup 表 |
| `bff/bff_service.py` | 持久化逻辑、移除 API Key |
| `bff/bounty_hub.py` | 确认结算流程 |

---

## 实施顺序

1. Task 4 (移除硬编码 API Key) - 快速简单
2. Task 3 (修改邻居发现逻辑) - 逻辑修改
3. Task 1 (确认结算流程) - 确认完整性
4. Task 2 (全局状态持久化) - 较大改动
5. Task 5 (容器健康监控) - 增强功能
