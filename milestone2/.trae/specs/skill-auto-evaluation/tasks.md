# Tasks

## 任务依赖关系

```
[Task 1] 数据库扩展
    ↓
[Task 2] 实现自动评分器
    ↓
[Task 3] 实现评分触发 API
    ↓
[Task 4] 修改 close_bounty 自动评分
    ↓
[Task 5] 前端排行榜视图
    ↓
[Task 6] 集成 SkillEditor
    ↓
[Task 7] 测试验证
```

---

## [Task 1] 数据库扩展

**目标**: 为 submissions 表添加评分字段

- [x] Task 1.1: 在 db.py 中添加数据库迁移语句，创建 score 和 score_reason 字段
- [x] Task 1.2: 验证 submissions 表包含 score（REAL）和 score_reason（TEXT）字段

**验证方法**:
```sql
PRAGMA table_info(submissions);
-- 应显示 score REAL 和 score_reason TEXT 字段
```

---

## [Task 2] 实现自动评分器 SubmissionEvaluator

**目标**: 创建 LLM-based 自动评分模块

- [x] Task 2.1: 创建 bff/evaluator.py 文件
- [x] Task 2.2: 实现 SubmissionEvaluator 类
  - [x] evaluate(bounty, submission) -> Tuple[float, str] 方法
  - [x] _call_llm(prompt) -> Tuple[float, str] 内部方法
- [x] Task 2.3: 实现 LLM 评分逻辑
  - [x] 构建评分提示词（完整性40%、准确性30%、可执行性30%）
  - [x] 调用 DeepSeek API 获取评分和理由
  - [x] 解析 JSON 响应 {score: int, reason: str}
- [x] Task 2.4: 添加详细日志输出
  - [x] 评分开始/结束日志
  - [x] 每个 submission 的评分结果日志

**评分提示词模板**:
```
你是一个任务评审专家。请根据以下悬赏要求和提交内容进行评分（0-100分），并给出简短理由。
悬赏描述：{bounty_desc}
提交内容：{submission_content}
评分标准：
- 完整性（40%）：是否完全满足任务要求
- 准确性（30%）：内容是否正确、无错误
- 可执行性（30%）：是否可以直接使用或执行
请严格按以下 JSON 格式输出，不要包含任何其他内容：
{{"score": 85, "reason": "内容完整准确，可直接执行"}}
```

---

## [Task 3] 实现评分触发 API

**目标**: 添加 POST /bounties/{id}/evaluate-submissions 接口

- [x] Task 3.1: 在 bff_service.py 中添加接口
  ```python
  @app.post("/bounties/{bounty_id}/evaluate-submissions")
  async def api_evaluate_submissions(bounty_id: str):
  ```
- [x] Task 3.2: 实现评分逻辑
  - [x] 查询 bounty 是否存在
  - [x] 查询所有未评分的 submission（score IS NULL）
  - [x] 遍历调用 SubmissionEvaluator.evaluate()
  - [x] 更新数据库 score 和 score_reason
- [x] Task 3.3: 添加错误处理
  - [x] 404: bounty 不存在
  - [x] 500: 评分失败
- [x] Task 3.4: 添加日志输出
  - [x] 找到多少个待评分 submission
  - [x] 每个 submission 的评分结果

**API 响应格式**:
```json
{"evaluated": 3}  // 成功评分的数量
```

---

## [Task 4] 修改 close_bounty 自动触发评分

**目标**: 悬赏关闭时自动执行评分流程

- [x] Task 4.1: 在 bounty_hub.py 的 close_bounty 方法中添加评分调用
  - [x] 在关闭悬赏前检查是否有未评分的 submission
  - [x] 如有未评分 submission，自动触发 _auto_evaluate_submissions
- [x] Task 4.2: 实现 _auto_evaluate_submissions 方法
  - [x] 遍历所有未评分 submission
  - [x] 调用 SubmissionEvaluator 评分
  - [x] 更新数据库
  - [x] 按分数排序返回结果
- [x] Task 4.3: 添加详细日志
  - [x] 评分开始/结束
  - [x] 每个 submission 的评分、排名

**日志格式示例**:
```
[BountyHub] [_auto_evaluate] 开始评级 3 个提交...
[BountyHub] [_auto_evaluate] 提交 1: id=xxx, 评分: 92, 理由: 内容完整准确
[BountyHub] [_auto_evaluate] 评级完成，排名: [xxx, yyy, zzz]
```

---

## [Task 5] 前端排行榜视图

**目标**: 在 BountyMarket.vue 中添加邻居反馈排行榜

- [x] Task 5.1: 修改 BountyMarket.vue，添加 submission-rank 卡片
- [x] Task 5.2: 实现 rankedSubmissions computed 属性
  - [x] 过滤出有评分的 submission
  - [x] 按 score 降序排序
- [x] Task 5.3: 实现 scoreTagType 方法
  - [x] score >= 80: 'success' (绿色)
  - [x] score >= 60: 'warning' (黄色)
  - [x] score < 60: 'danger' (红色)
- [x] Task 5.4: 实现 openSkillEditor 方法
  - [x] 设置 selectedSubmissionId
  - [x] 调用 skillEditorRef.openDialog()
- [x] Task 5.5: 添加 SkillEditor 组件引用
  - [x] import SkillEditor from './SkillEditor.vue'
  - [x] 添加 ref="skillEditorRef"
  - [x] 添加 selectedSubmissionId ref

---

## [Task 6] 集成 SkillEditor 支持多来源

**目标**: 修改 SkillEditor.vue 支持基于选中的 submission 创建 Skill

- [x] Task 6.1: 修改 SkillEditor.vue，添加 selectedSubmissionId prop
- [x] Task 6.2: 添加选中 submission 的信息显示
  - [x] selectedNeighborName: 从 submission 获取 agent_id
  - [x] selectedScore: 从 submission 获取 score
  - [x] neighborContent: 从 submission 获取 content
- [x] Task 6.3: 修改 openDialog 方法
  - [x] 如果有 submissionId，从 submissions 列表中查找
  - [x] 自动填充表单字段（name, capability, usage 等）
  - [x] 显示邻居反馈来源信息
- [x] Task 6.4: 调整 skill 保存逻辑
  - [x] 提交时包含 source_submission_id
  - [x] 确保 submission_id 正确传递到后端

---

## [Task 7] 测试验证

**目标**: 端到端验证整个评分和 Skill 整理流程

- [ ] Task 7.1: 验证数据库扩展
  - [ ] 确认 submissions 表包含 score 和 score_reason 字段
- [ ] Task 7.2: 测试评分 API
  - [ ] POST /bounties/{id}/evaluate-submissions
  - [ ] 检查日志输出
  - [ ] 验证数据库更新
- [ ] Task 7.3: 测试 close_bounty 自动评分
  - [ ] 调用关闭悬赏接口
  - [ ] 验证自动触发评分
  - [ ] 检查日志
- [ ] Task 7.4: 测试前端排行榜
  - [ ] 打开悬赏详情页
  - [ ] 验证排行榜显示
  - [ ] 验证评分颜色标签
- [ ] Task 7.5: 测试 Skill 整理流程
  - [ ] 点击"基于此项整理 Skill"
  - [ ] 验证编辑器打开并填充内容
  - [ ] 保存 Skill 并验证

**测试日志验证点**:
```
[BountyHub] [_auto_evaluate] 开始评级 N 个提交...
[BountyHub] [_auto_evaluate] 提交 X: id=xxx, 评分: YY, 理由: "..."
[BountyHub] [_auto_evaluate] 评级完成，排名: [xxx, yyy, zzz]
```

---

## Task 优先级

1. **高优先级**: Task 1-4 (后端核心功能) ✅ 已完成
2. **中优先级**: Task 5-6 (前端 UI) ✅ 已完成
3. **低优先级**: Task 7 (测试验证) ⏳ 待验证

---

## 关键技术点

| 任务 | 技术点 |
|------|--------|
| Task 2 | LLM API 调用、JSON 解析、异常处理 |
| Task 3 | FastAPI 路由、异步编程、数据库事务 |
| Task 4 | 异步任务编排、日志规范 |
| Task 5 | Vue Composition API、Element Plus 表格 |
| Task 6 | Vue Props、组件通信 |
