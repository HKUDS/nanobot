# 悬赏结算结果显示功能 Spec

## Why
悬赏任务结算完成后，需要在前端显示结算结果（评分、奖励发放等），让用户直观看到任务完成情况。

## What Changes
- 在悬赏详情或方案列表中显示每个提交的评分和理由
- 显示奖励发放状态
- 显示任务结算状态（已完成/已关闭）

## Impact
- Affected specs: bounty system
- Affected code: `frontend/src/components/BountyMarket.vue`

## ADDED Requirements

### Requirement: 悬赏结算结果展示
系统 SHALL 在悬赏关闭后显示结算结果

#### Scenario: 查看已关闭悬赏的结算结果
- **WHEN** 用户查看状态为 `closed` 的悬赏
- **THEN** 显示该悬赏的结算结果，包括：
  - 每个提交的评分 (`score`)
  - 评分理由 (`score_reason`)
  - 奖励发放金额
  - 最终等级 (`final_grade`)

### Requirement: 方案列表显示评分
系统 SHALL 在方案列表中显示每个提交的评分信息

#### Scenario: 查看悬赏的方案列表
- **WHEN** 用户点击"查看方案"按钮
- **THEN** 方案列表中显示：
  - 评分（数值）
  - 评分理由
  - 奖励金额

## MODIFIED Requirements

### Requirement: 悬赏状态显示
悬赏状态字段 `status` 为 `closed` 时，前端应显示为"已结算"

## Technical Notes
- 评分数据从 `/bounties/{id}/submissions` 接口获取
- 字段：`score`, `score_reason`, `reward_amount`, `final_grade`
