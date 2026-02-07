# 每日对话总结功能规范

## 功能概述

本规范定义了 nanobot 自动每日对话总结功能的需求。该功能在对话结束后自动生成结构化的每日概要，提取关键信息并保存到文件中。

## ADDED Requirements（新增需求）

---

### Requirement: 自动触发总结

系统 SHALL 在满足触发条件时自动启动对话总结流程。

#### Scenario: 消息计数触发

- **WHEN** 用户发送的消息数量达到配置的间隔值（默认为 10 条消息）
- **THEN** 系统异步启动总结任务，不阻塞主对话流程
- **AND** 重置该会话的消息计数器

#### Scenario: 手动触发

- **WHEN** 用户发送明确的总结请求（如"总结今天的对话"、"生成每日概要"）
- **THEN** 立即启动总结任务，忽略消息计数
- **AND** 不影响主对话响应速度

---

### Requirement: 模型配置

系统 SHALL 支持灵活配置总结任务使用的 LLM 模型。

#### Scenario: 环境变量配置

- **WHEN** 环境变量 `NANOBOT_SUMMARY_MODEL` 已设置
- **THEN** 系统使用该环境变量指定的模型进行总结
- **AND** 该配置优先级最高

#### Scenario: 配置文件配置

- **WHEN** 配置文件中 `agents.summary.model` 已设置
- **THEN** 系统使用该配置的模型进行总结
- **AND** 该配置优先级次高

#### Scenario: 回退到主对话模型

- **WHEN** 环境变量和配置文件中的总结模型都未设置
- **THEN** 系统使用 `agents.defaults.model`（主对话使用的模型）进行总结
- **AND** 这确保总结质量与主对话保持一致

---

### Requirement: 话题提取

系统 SHALL 从对话中识别和提取主要讨论话题。

#### Scenario: 话题聚类

- **WHEN** 分析一天内的对话消息
- **THEN** 系统识别 3-5 个主要讨论话题
- **AND** 每个话题包含简短描述和相关的对话轮次

#### Scenario: 话题格式

- **WHEN** 生成每日概要文件
- **THEN** 话题部分使用清晰的列表格式
- **AND** 每个话题不超过 50 个字符

---

### Requirement: 用户偏好提取

系统 SHALL 识别和记录用户的偏好和设置。

#### Scenario: 显式偏好

- **WHEN** 用户明确表达偏好（如"我喜欢简洁的回答"、"我偏好使用中文"）
- **THEN** 系统提取并记录到偏好部分
- **AND** 标注为"用户偏好"

#### Scenario: 隐式偏好

- **WHEN** 用户多次选择特定的模型、工具或响应风格
- **THEN** 系统推断并记录为观察到的偏好
- **AND** 标注为"观察到的偏好"

---

### Requirement: 重要决定提取

系统 SHALL 识别对话中达成的重要决定或结论。

#### Scenario: 技术决定

- **WHEN** 用户或 AI 做出技术选择（如使用某个模型、采用某种方案）
- **THEN** 记录决定内容和理由
- **AND** 标注为"技术决定"

#### Scenario: 用户决策

- **WHEN** 用户做出明确决定（如"我将使用方案A"、"决定今天开始"）
- **THEN** 记录决定内容和背景
- **AND** 标注为"用户决策"

---

### Requirement: 待办事项提取

系统 SHALL 从对话中提取待办事项或任务。

#### Scenario: 明确任务

- **WHEN** 用户明确提到需要做的事情（如"我需要完成X"、"记得提醒我Y"）
- **THEN** 记录为未完成的待办事项
- **AND** 使用清晰的动词开头的描述

#### Scenario: 隐式任务

- **WHEN** 从对话中识别出的行动项或承诺
- **THEN** 记录为识别到的任务
- **AND** 标注为"识别到的任务"

---

### Requirement: 技术问题记录

系统 SHALL 识别和记录技术问题及解决方案。

#### Scenario: 问题识别

- **WHEN** 讨论中遇到技术问题或错误
- **THEN** 记录问题描述和上下文
- **AND** 标注为"问题"

#### Scenario: 解决方案

- **WHEN** 讨论中找到或提出了解决方案
- **THEN** 记录解决方案或解决步骤
- **AND** 关联到相应的问题

---

### Requirement: 每日概要格式

系统 SHALL 生成标准化的 Markdown 格式每日概要文件。

#### Scenario: 文件结构

- **WHEN** 创建每日概要文件
- **THEN** 文件命名为 `memory/YYYY-MM-DD.md`
- **AND** 包含以下标准章节：
  1. 📌 主要话题
  2. 👤 用户偏好
  3. ✅ 重要决定
  4. 📋 待办事项
  5. 🔧 技术问题与解决
  6. 💡 关键洞察
  7. 生成时间戳

#### Scenario: 内容追加

- **WHEN** 同一天内多次触发总结
- **THEN** 使用追加模式，不覆盖已有内容
- **AND** 每次添加分隔符和时间戳

---

### Requirement: 异步执行

系统 SHALL 异步执行总结任务，不影响主对话响应时间。

#### Scenario: 子代理执行

- **WHEN** 触发总结任务
- **THEN** 通过 `SubagentManager` 在独立的上下文中执行
- **AND** 使用配置的总结模型
- **AND** 主对话循环继续响应用户

#### Scenario: 非阻塞

- **WHEN** 总结任务正在执行
- **THEN** 主对话流程不被阻塞
- **AND** 用户可以继续发送新消息
- **AND** 总结失败不影响主对话功能

---

### Requirement: 配置验证

系统 SHALL 在启动时验证总结配置的有效性。

#### Scenario: 模型名称验证

- **WHEN** `NANOBOT_SUMMARY_MODEL` 或 `agents.summary.model` 已设置
- **THEN** 验证模型名称包含有效的提供商前缀
- **AND** 如无效，记录警告并使用回退值
- **AND** 支持的格式：`provider/model`（如 `deepseek/deepseek-chat`）

#### Scenario: 间隔范围验证

- **WHEN** `NANOBOT_SUMMARY_INTERVAL` 或 `agents.summary.interval` 已设置
- **THEN** 验证值为整数且在 0-100 范围内
- **AND** 如超出范围，记录警告并使用默认值（10）

---

### Requirement: 成本控制

系统 SHALL 提供机制以控制总结任务的成本。

#### Scenario: 最大 Token 限制

- **WHEN** 配置文件中设置了 `agents.summary.maxTokens`
- **THEN** 总结请求使用该最大 token 限制
- **AND** 避免因模型输出过长导致成本过高

#### Scenario: 默认优化

- **WHEN** 未配置最大 token
- **THEN** 使用合理的默认值（4000 tokens）
- **AND** 根据总结模型的大小调整

---

### Requirement: 错误处理

系统 SHALL 妥善处理总结任务中的错误。

#### Scenario: 总结失败

- **WHEN** 总结任务因 API 错误、超时或其他原因失败
- **THEN** 记录错误日志
- **AND** 不影响主对话功能
- **AND** 允许下次触发时重试

#### Scenario: 文件写入失败

- **WHEN** 写入每日概要文件失败（如权限问题）
- **THEN** 记录详细错误信息
- **AND** 尝试写入备用位置或通知用户

---

### Requirement: 禁用机制

系统 SHALL 支持完全禁用自动总结功能。

#### Scenario: 环境变量禁用

- **WHEN** 环境变量 `NANOBOT_AUTO_SUMMARY` 设置为 `false`
- **THEN** 完全禁用自动总结触发
- **AND** 不检查消息计数
- **AND** 仍支持手动触发

#### Scenario: 配置文件禁用

- **WHEN** 配置文件中 `agents.summary.enabled` 设置为 `false`
- **THEN** 禁用自动总结功能
- **AND** 不干扰手动记忆操作
