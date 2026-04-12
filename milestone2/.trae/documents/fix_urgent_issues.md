# 紧急修复计划

## 问题 1: 数据库缺少 score 字段

### 分析
```
[BountyHub] [_auto_evaluate] 开始评级 3 个提交...
[Evaluator] 评分完成: score=30.0, reason=内容过短
[BFF] 关闭悬赏任务异常: no such column: score
```

评分成功了（30.0），但保存时数据库表没有 score 字段。

### 修复
在 `db.py` 的 `init_db()` 中添加 `score` 和 `score_reason` 字段到 `submissions` 表。

---

## 问题 2: 容器 CONVERSATION_ID=unknown

### 分析
```
[AgentLoop] 初始化成功 for conversation=unknown
```

容器启动时没有正确设置 `CONVERSATION_ID` 环境变量，导致：
1. 通知发送到 `/notifications/unknown`
2. 容器获取自己的通知时查不到
3. 任务没有被处理

### 修复
1. 检查容器启动脚本/配置
2. 确保 `CONVERSATION_ID` 环境变量被正确传递
3. 可能的配置位置：
   - docker-compose.yml
   - 容器启动脚本
   - k8s deployment

---

## 修复任务

### Task 1: 添加 score 字段到数据库
- [ ] 检查 db.py 中 submissions 表的定义
- [ ] 确保包含 score 和 score_reason 字段
- [ ] 如果不存在，添加 ALTER TABLE 语句

### Task 2: 检查容器启动配置
- [ ] 检查 docker-compose 或启动脚本
- [ ] 确保 CONVERSATION_ID 被传递

### Task 3: 手动修复现有数据库
- [ ] 对已有数据库执行 ALTER TABLE

---

## 修复文件

| 文件 | 修改内容 |
|------|----------|
| `bff/db.py` | 确保 submissions 表包含 score, score_reason 字段 |

---

## 注意事项

1. 评分功能是正常的（返回了 30.0），只是无法保存到数据库
2. 容器 CONVERSATION_ID 问题需要在部署层面解决
