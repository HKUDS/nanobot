# Checklist

## 数据库扩展
- [x] submissions 表包含 score 字段（REAL 类型）
- [x] submissions 表包含 score_reason 字段（TEXT 类型）

## 后端评分器
- [x] evaluator.py 文件创建成功
- [x] SubmissionEvaluator 类实现 evaluate 方法
- [x] LLM API 调用逻辑正确
- [x] 日志输出格式正确

## 评分 API
- [x] POST /bounties/{id}/evaluate-submissions 接口存在
- [x] 接口正确遍历所有未评分 submission
- [x] 评分结果正确写入数据库
- [x] 错误处理完善

## close_bounty 扩展
- [x] close_bounty 方法自动触发评分
- [x] 评分在任务关闭前完成
- [x] 日志输出完整

## 前端排行榜
- [x] submission-rank 卡片组件存在
- [x] rankedSubmissions 按评分降序排列
- [x] 评分标签样式正确（高分绿色，低分红色）
- [x] "基于此项整理 Skill"按钮存在且功能正确

## SkillEditor 集成
- [x] SkillEditor 支持 selectedSubmissionId prop
- [x] 显示选中邻居的名称和评分
- [x] openDialog 方法正确获取反馈内容
- [x] 提交时 submission_id 正确传递

## 端到端测试
- [ ] 发布悬赏任务
- [ ] 邻居节点反馈内容
- [ ] 触发评分接口
- [ ] 查看排行榜显示正确
- [ ] 基于反馈整理 Skill 成功
- [ ] BFF 日志输出完整
