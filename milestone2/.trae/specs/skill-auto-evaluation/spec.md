# Skill 可视化沉淀计划（含自动评分与多邻居聚合）

## Why
当前系统无法对多个邻居节点的反馈进行质量评估和排序，导致发布者难以快速筛选最佳反馈来总结 Skill。需要增加自动评分机制，辅助发布者挑选高质量反馈。

## What Changes
- 数据库扩展：为 `submissions` 表增加 `score` 和 `score_reason` 字段
- 新增后端模块：`SubmissionEvaluator` 自动评分器
- 新增 API：`POST /bounties/{id}/evaluate-submissions` 触发评分
- 前端增强：`BountyMarket.vue` 增加邻居反馈排行榜视图
- 前端组件调整：`SkillEditor.vue` 支持多来源选择

## Impact
- Affected specs: 悬赏系统、Skill 知识库
- Affected code: `bounty_hub.py`, `bounty_evaluator.py`, `bff_service.py`, `BountyMarket.vue`, `SkillEditor.vue`, `db.py`

---

## ADDED Requirements

### Requirement: 自动评分模块
系统 SHALL 提供自动评分功能，对悬赏任务的每个邻居反馈进行质量评估（0-100分）并附带评分理由。

#### Scenario: 评分流程
- **WHEN** 发布者调用评分接口或悬赏关闭时
- **THEN** 系统对所有未评分的 submission 进行评分，结果写入数据库

### Requirement: 排行榜展示
系统 SHALL 在前端展示邻居反馈排行榜，按评分降序排列。

#### Scenario: 查看排行榜
- **WHEN** 用户打开悬赏详情页
- **THEN** 显示所有邻居反馈的评分、理由，并支持选择任意一条来整理 Skill

### Requirement: Skill 整理
系统 SHALL 支持发布者基于选中的邻居反馈内容总结 Skill 并存储到公共知识库。

#### Scenario: 整理 Skill
- **WHEN** 用户选择一条反馈并点击"基于此项整理 Skill"
- **THEN** 打开 Skill 编辑器，自动填充该反馈内容供用户编辑总结

---

## MODIFIED Requirements

### Requirement: close_bounty 流程扩展
悬赏关闭时 SHALL 自动触发评分流程（如果尚未评分）。

#### Scenario: 关闭悬赏
- **WHEN** 发布者调用关闭悬赏接口
- **THEN** 系统自动对所有未评分的 submission 进行评分，然后执行原有结束流程

---

## REMOVED Requirements
无

---

## 数据结构设计

### submissions 表扩展
```sql
ALTER TABLE submissions ADD COLUMN score REAL;           -- 自动评分（0-100）
ALTER TABLE submissions ADD COLUMN score_reason TEXT;    -- 评分理由
```

### Skill 结构
```python
{
    "id": "uuid",
    "name": "技能名称",
    "capability": "能力描述",
    "usage": "使用方法",
    "source_submission_id": "选中的邻居节点submission_id",
    "curated_by": "发布节点id",
    "created_at": "2024-01-01"
}
```

---

## 关键改动点总结

| 改动项 | 说明 |
|--------|------|
| 数据库 | submissions 表增加 score 和 score_reason 字段 |
| 新增模块 | `SubmissionEvaluator` 自动评分器 |
| 前端界面 | 增加邻居反馈排行榜表格，支持多选一整理 |
| 业务流程 | 增加"自动评分→用户选择最佳反馈→手动总结"环节 |
