# BFF Service 日志清单

## 容器管理
- `[BFF] KM容器端口从orchestrator恢复: {km_container_id}, 端口: {port}`
- `[BFF] KM容器不存在，创建中...`
- `[BFF] KM容器已创建: {km_container_id}, 端口: {container_ports.get(km_container_id)}`
- `[BFF] KM容器创建失败 (attempt {attempt+1}/{max_retries}): {e}`
- `[BFF] Consolidator容器已存在: {consolidator_conv_id}`
- `[BFF] 创建Consolidator容器...`
- `[BFF] Consolidator容器已创建: {consolidator_conv_id}` (打印3次)
- `[BFF] Consolidator容器创建失败 (attempt {attempt+1}/{max_retries}): {e}`

## 对话管理
- `[BFF] 初始化数据库...`
- `[BFF] 启动时清理无效对话...`
- `[BFF] 删除无效对话 {conv_id}，容器状态: {container.status}`
- `[BFF] 删除无效对话 {conv_id}，容器不存在: {e}`
- `[BFF] 清理完成，剩余对话: {len(conversations)}`
- `[BFF] 开始迁移对话数据，补充 Power 机制字段...`
- `[BFF] 迁移对话 {conv_id} 的 Power 字段`
- `[BFF] 迁移完成，共处理 {len(conversations)} 个对话`
- `[BFF] 自动建立邻居关系: {conversation_id} <-> {new_conversation_id}`
- `[BFF] 建立邻居关系失败: {e}`
- `[BFF] Fork error: {e}`
- `[BFF] Merge error: {e}`

## 后台任务
- `[BFF] 启动定时邻居发现任务`
- `[BFF] 启动容器健康监控任务`
- `[BFF] 容器健康检查失败: {e}`
- `[BFF] 容器不健康 {conv_id}: {container.status}`
- `[BFF] 容器不存在 {conv_id}: {e}`
- `[BFF] 健康检查: {len(conv_ids)} 个容器中 {unhealthy_count} 个不健康`
- `[BFF] 健康检查: 所有 {len(conv_ids)} 个容器运行正常`
- `[BFF] 邻居发现失败: {e}`
- `[BFF] 邻居发现: 节点数量不足 ({len(all_nodes)})，跳过`
- `[BFF] 补充父子邻居关系: {node_id} <-> {parent_id}`
- `[BFF] 建立邻居关系失败 ({node_id} <-> {parent_id}): {e}`
- `[BFF] 邻居发现完成，新增 {new_connections} 个连接`
- `[BFF] 邻居发现: 所有父子关系已建立`

## Power 机制
- `[Power] Reward: {score}, Delta: {delta}`

## 文件监控
- `[BFF] 文件监控失败: {e}`

## PublicMemory 操作
- `[BFF] PUBLIC_MEMORY_HOST_PATH env: {pm_host_path}`
- `[BFF] 读取PublicMemory路径: {pm_path}, exists={pm_path.exists()}`
- `[BFF] 读取PublicMemory (物理路径): {pm_path}, top_k={top_k}`
- `[BFF] PublicMemory文件不存在: {pm_path}`
- `[BFF] 读取PublicMemory完成: {len(entries)} 条记录`
- `[BFF] 读取PublicMemory失败: {e}`
- `[BFF] 写入PublicMemory (物理路径): {pm_path}`
- `[BFF] 原子替换PublicMemory: {len(entries)} 条记录 -> {pm_path}`
- `[BFF] 替换PublicMemory失败: {e}`
- `[BFF] 获取Skill 0失败: {e}`

## Chat/对话
- `[BFF] 协作者检索到 {len(skills_result['entries'])} 条Skill`
- `[BFF] Skill检索失败: {e}`
- `[BFF] Chat error: {e.response.status_code} - {e.response.text}`
- `[BFF] Chat timeout: {url}`
- `[BFF] Chat error: {url} - {str(e)}`

## NodeRelation
- `[NodeRelation] 添加关系: {req.source_node_id} -> {req.target_node_id}, weight={req.weight}`
- `[NodeRelation] 添加关系失败: {e}`
- `[NodeRelation] 获取邻居: node_id={node_id}`
- `[NodeRelation] 获取邻居失败: {e}`
- `[NodeRelation] 获取所有关系失败: {e}`

## Notification
- `[Notification] 更新状态为 processing: {notification_id}`
- `[Notification] 更新状态失败: {e}`
- `[Notification] 更新状态为 completed: {notification_id}`
- `[Notification] 更新状态失败: {e}`

## Bounty/悬赏任务
- `[BFF] 关闭悬赏任务: bounty_id={bounty_id}, issuer={req.issuer_id}`
- `[BFF] 悬赏任务关闭成功: {result}`
- `[BFF] 关闭悬赏任务失败: {e}`
- `[BFF] 关闭悬赏任务异常: {e}`
- `[Bounty] 手动整理 skill: bounty_id={bounty_id}`
- `[Bounty]   name: {req.name}`
- `[Bounty]   capability: {req.capability}`
- `[Bounty]   usage: {req.usage}`
- `[Bounty]   submission_id (邻居节点): {req.submission_id}`
- `[Bounty] Skill 导出成功：{export_path}`
- `[Bounty] Skill 导出失败：{e}`
- `[Bounty] Skill 保存成功：doc_id={doc_id}`
- `[Bounty] Skill 保存失败: {e}`

## Evaluator API
- `[Evaluator API] 开始评分: bounty_id={bounty_id}`
- `[Evaluator API] 找到 {len(submissions)} 个未评分的提交`
- `[Evaluator API] 没有需要评分的提交`
- `[Evaluator API] 提交 {sub['id']} 评分完成: score={score}, reason={reason}`
- `[Evaluator API] 评分完成，共 {len(submissions)} 个提交`
- `[Evaluator API] 评分失败: {e}`

## Skill API
- `[BFF] 获取所有 skill`
- `[BFF] 返回 {len(skills)} 个 skill`
- `[BFF] 获取 skill 列表失败: {e}`
- `[BFF] 获取 skill: skill_id={skill_id}`
- `[BFF] 获取 skill 失败: {e}`

## KM (KnowledgeManager) 转发
- `[KM] 预置0号Skill，转发到KM容器`
- `[BFF] 转发 preset-skill-0 失败: {e}`
- `[BFF] 获取KM URL失败: {e}`
- `[BFF] 转发 submit-page 失败：{e}`
- `[BFF] 转发 heap-written 失败：{e}`
- `[BFF] 转发 allocate_page 失败: {e}`
- `[BFF] 转发 active_pages 失败: {e}`
- `[BFF] 转发 mark_pages_merged 失败: {e}`
- `[BFF] 转发 task 失败: {e}`

## 搜索
- `[BFF] 搜索失败: {e}`

## 统计
- `[BFF] 转发 stats 失败: {e}`

## 合并
- `[BFF] 转发 force-merge 失败: {e}`
- `[BFF] 转发合并请求到Consolidator: {merge_url}`
- `[BFF] Consolidator合并完成: {result}`
