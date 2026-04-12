标注工作流（HIL）与智能体 Power 机制技术方案
一、概述
在现有轨迹标注功能基础上，为每个智能体（即每个对话容器/分支）引入 Power 评分机制。Power 是一个综合评分，反映该智能体在历史交互中的表现质量，由以下因素动态计算：

对话过程中模型自评的 prm_score.value（0~1）

用户通过 HIL 标注的标签（如 Bug 扣分、Creative 加分）

任务完成度（可选，如工具调用成功率）

Power 值可被用于：

前端展示，让用户直观了解每个分支的“能力”或“可靠性”。

后续强化学习中的初始权重或采样策略。

作为群体智能中“共识技能”的筛选依据（高 Power 分支的轨迹更可信）。

二、Power 定义与计算
2.1 基本公式
每个智能体（容器）的 Power 是一个 0~100 的浮点数，初始值为 50（中性）。每次对话轮次结束后，根据该轮次的 reward 和用户标注动态更新。

单轮更新公式：

text
Δpower = α * (reward_norm - 0.5) + β * (annotation_score)
reward_norm：模型自评 prm_score.value（0~1），已归一化。

annotation_score：用户标注带来的分数（见 2.2）。

α、β：权重系数（可配置，例如 α = 0.6，β = 0.4）。

累积更新：Power 采用指数移动平均（EMA），避免单轮波动过大：

text
Power_new = γ * Power_old + (1-γ) * (Power_old + Δpower)
其中 γ 为衰减因子（如 0.9），使长期表现占主导。

2.2 标注到分数的映射
标签	分值	说明
Bug	-5	明显的错误或失败
Misleading	-3	回答具有误导性
Creative	+2	创新的解决方案
Helpful	+1	普通有用回答
Efficient	+2	工具调用高效、Token 少
自定义标签	可配置	用户自定义标签时弹窗设定分数
2.3 Power 等级
为了直观展示，可将 Power 值映射为等级：

Power 范围	等级	图标/颜色
90–100	S	金色星星
75–89	A	绿色向上箭头
50–74	B	蓝色圆圈
25–49	C	橙色警告
0–24	D	红色叉号
三、数据存储
3.1 扩展 conversations 元数据
在 BFF 的 conversations 字典中为每个分支增加字段：

python
conversations[conv_id] = {
    ...原有字段...,
    "power": 50.0,           # 当前 Power 值
    "power_history": [       # 可选，存储历史 Power 快照
        {"timestamp": "...", "value": 50.0}
    ],
    "total_annotations": 0,  # 累计标注次数（用于加权）
}
3.2 标注表增加 power_delta 字段
在 annotations 表中，记录每次标注引起的 Power 变化量：

sql
ALTER TABLE annotations ADD COLUMN power_delta REAL;
这样便于追溯 Power 变化原因。

四、更新时机与流程
4.1 自动更新（基于模型自评）
每次对话完成后（/chat 接口返回前），BFF 调用 orchestrator 的更新 Power 方法：

python
async def update_power_after_conversation(conversation_id: str, reward: float):
    conv = conversations[conversation_id]
    old_power = conv["power"]
    reward_norm = reward  # 已经是 0~1
    delta = ALPHA * (reward_norm - 0.5)   # α = 0.6
    new_power = old_power + delta
    # 限制范围 0~100
    new_power = max(0, min(100, new_power))
    conv["power"] = new_power
    # 记录历史
    conv.setdefault("power_history", []).append({
        "timestamp": datetime.now().isoformat(),
        "value": new_power,
        "reason": f"auto_reward_{reward_norm}"
    })
4.2 手动更新（基于用户标注）
当用户添加或删除标签时，触发 Power 更新：

python
async def update_power_by_annotation(conversation_id: str, step: int, label: str, is_add: bool):
    delta = LABEL_SCORE_MAP.get(label, 0)
    if not is_add:
        delta = -delta   # 删除标签则回退
    conv = conversations[conversation_id]
    old_power = conv["power"]
    new_power = old_power + BETA * delta   # β = 0.4
    new_power = max(0, min(100, new_power))
    conv["power"] = new_power
    # 记录
    conv["power_history"].append({
        "timestamp": datetime.now().isoformat(),
        "value": new_power,
        "reason": f"annotation_{label}_{'add' if is_add else 'remove'}"
    })
4.3 批量重算（可选）
如果发现 Power 计算规则调整，可提供重新计算所有分支 Power 的后台任务。

五、前端展示
5.1 分支列表中的 Power 显示
在左侧分支栏（对话历史列表）中，每个分支名称旁显示 Power 值及等级图标。

例如：

text
对话-10:30  🔵 B (67)
分支-技术方案 🟢 A (82)
5.2 轨迹卡片中的标注与 Power 影响提示
每个 ACTION 和 OBSERVATION 卡片底部显示已添加的标签，并可添加新标签。

当用户添加/删除标签时，实时刷新该分支的 Power 值（通过 WebSocket 或轮询更新）。

5.3 Power 趋势图
在分支详情页（或侧边栏）增加一个折线图，展示 power_history 中 Power 值随时间的变化，帮助用户了解智能体的成长过程。

六、接口设计
6.1 获取分支 Power 信息
python
@app.get("/conversations/{conversation_id}/power")
async def get_power(conversation_id: str):
    conv = conversations.get(conversation_id)
    if not conv:
        raise HTTPException(404)
    return {"power": conv["power"], "history": conv.get("power_history", [])}
6.2 添加标注（自动更新 Power）
python
@app.post("/annotations")
async def add_annotation(req: AnnotationCreate):
    # 存储标注
    annotation_id = save_annotation(...)
    # 更新 Power
    await update_power_by_annotation(req.conversation_id, req.step, req.label, is_add=True)
    return {"id": annotation_id, "power_delta": LABEL_SCORE_MAP.get(req.label, 0)}
6.3 删除标注（自动回退 Power）
python
@app.delete("/annotations/{id}")
async def delete_annotation(id: int):
    annotation = get_annotation(id)
    await update_power_by_annotation(annotation.conversation_id, annotation.step, annotation.label, is_add=False)
    delete_annotation_from_db(id)
    return {"status": "deleted"}
七、Reward 信号回写（与 Power 联动）
Power 本身就是对智能体整体表现的量化，可直接作为 RL 训练的额外奖励信号。例如：

在离线训练中，对于高 Power 分支的轨迹赋予更高采样权重。

在在线学习时，将当前分支的 Power 作为探索-利用的 bias（高 Power 更倾向利用，低 Power 鼓励探索）。

也可以在 trajectory.jsonl 中为每条轨迹增加 power_at_time 字段，记录当时智能体的 Power 值，用于事后分析。

八、实施计划
阶段	任务	预估工时
1	后端扩展 conversations 元数据，增加 Power 字段和更新逻辑	0.5天
2	实现 Power 自动更新（对话后）和手动更新（标注后）	0.5天
3	前端分支列表显示 Power 和等级图标	0.5天
4	前端标注组件增加标签选择及 Power 变化提示	1天
5	Power 趋势图（ECharts 或类似）	0.5天
6	测试与文档	0.5天
九、总结
通过引入 Power 机制，系统能够量化每个智能体分支的表现质量，并随着用户反馈和模型自评动态演化。这不仅增强了可观测性，还为后续的强化学习、群体智能、共识技能提炼提供了重要的元数据支撑。同时，Power 与 HIL 标注紧密耦合，形成“人机协同”的闭环优化。