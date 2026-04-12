好的，我已理解您的新增需求：**发布节点需要能够自动审阅多个邻居节点的反馈内容，并进行自动评分，从而辅助发布者挑选最佳反馈来总结 Skill**。

这意味着我们将保留原有的“手动整理 Skill”流程，但在其上游增加一个 **“自动评分与结果聚合”** 的中间步骤。以下是将该想法整合进原有方案后的**完整版技术设计文档**。

---

# Skill 可视化沉淀计划（含自动评分与多邻居聚合·完整版）

## 1. 业务流程（增强版）

```
发布节点发起悬赏
       ↓
多个邻居节点自动接手任务（notify_neighbors）
       ↓
邻居节点执行并反馈内容（submission）
       ↓
【新增】发布节点自动审阅所有邻居反馈 → 自动评分并排序展示
       ↓
发布节点选择最佳反馈（或任意反馈）作为参考
       ↓
发布节点根据选中的反馈内容【总结】出 Skill
       ↓
Skill 沉淀到公共知识库
```

**关键变化说明：**
- 邻居节点由原来的“唯一来源”变为“多源”。
- 增加 **自动评分机制**：后端调用 AI 模型或规则引擎对每个 `submission` 进行质量评估。
- 发布者在前端看到一个**排行榜视图**，可以对比不同邻居的结果并选择其一来总结 Skill。

---

## 2. Skill 的定义（不变）

**Skill = AI Agent 的可执行能力模块**

**Skill = AI Agent 的可执行能力模块**

| 特性 | 说明 |
|------|------|
| 模块化能力单元 | 可复用、可组合的功能组件 |
| 场景最佳实践 | 将抽象任务转化为可执行操作的封装 |
| 工具接口 | 不是知识，而是能做事的接口 |
| 输入/输出契约 | 有明确的接口定义和执行逻辑 |

**Skill 不一定是代码**，可以是：
- 操作流程
- 最佳实践
- 方法论
- 工具调用接口
- 执行策略


---

## 3. 数据结构设计（扩展）

### 3.1 Submission 表扩展（新增评分字段）

在原 `submissions` 表中增加以下字段：

```sql
ALTER TABLE submissions ADD COLUMN score REAL;           -- 自动评分（0-100）
ALTER TABLE submissions ADD COLUMN score_reason TEXT;    -- 评分理由（供发布者参考）
```

### 3.2 Skill 结构（调整来源字段语义）

```python
{
    "id": "uuid",
    "name": "image_processing",
    "capability": "能够识别、裁剪、压缩图片",
    "usage": "1. 调用 process_image()...",
    "source_submission_id": "选中的邻居节点submission_id",  # 此时为用户主动选择的最佳反馈
    "curated_by": "发布节点id",
    "created_at": "2024-01-01"
}
```

---

## 4. 自动评分模块设计（新增核心）

### 4.1 评分触发时机

当悬赏任务的所有邻居提交完毕（或发布者主动触发评分）时，后端对每个未评分的 submission 进行异步评分。

**触发接口示例：**
```
POST /bounties/{bounty_id}/evaluate-submissions
```

### 4.2 评分策略（可插拔设计）

考虑到不同任务类型（代码生成、文本创作、数据分析）评分标准不同，建议采用 **策略模式 + LLM 评分**。

```python
class SubmissionEvaluator:
    async def evaluate(self, bounty: dict, submission: dict) -> tuple[float, str]:
        """
        返回: (score, reason)
        """
        prompt = f"""
        你是一个任务评审专家。请根据以下悬赏要求和提交内容进行评分（0-100分），并给出简短理由。

        悬赏描述：{bounty['description']}
        提交内容：{submission['content']}

        评分标准：
        - 完整性（40%）：是否完全满足任务要求
        - 准确性（30%）：内容是否正确、无错误
        - 可执行性（30%）：是否可以直接使用或执行

        请按 JSON 格式输出：{{"score": 85, "reason": "..."}}
        """
        # 调用 LLM API...
        return score, reason
```

**备选方案**：对于简单任务（如计算题），可使用规则引擎（如正则匹配答案、执行时间比较）。

### 4.3 评分结果存储与展示

- 评分结果写入 `submissions.score` 和 `submissions.score_reason`。
- 前端在悬赏详情页新增 **“邻居反馈排行榜”** 区域，展示所有邻居提交及其评分。

---

## 5. 前端实现（更新）

### 5.1 BountyMarket.vue 增加反馈聚合视图

```vue
<template>
  <div class="bounty-detail">
    <!-- 原有内容... -->

    <!-- 新增：邻居反馈排行榜（自动评分结果） -->
    <el-card class="submission-rank" header="邻居节点反馈与评分">
      <el-table :data="rankedSubmissions" stripe>
        <el-table-column type="index" label="排名" width="60" />
        <el-table-column prop="neighbor_name" label="节点名称" width="150" />
        <el-table-column prop="score" label="评分" width="100">
          <template #default="{ row }">
            <el-tag :type="scoreTagType(row.score)">{{ row.score }}分</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score_reason" label="评分理由" show-overflow-tooltip />
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openSkillEditor(row)">
              基于此项整理 Skill
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- Skill 编辑器组件（原有，但传入选中的 submission） -->
    <SkillEditor ref="skillEditorRef" :bounty-id="bountyId" :issuer-id="currentConvId"
                 :submission-id="selectedSubmissionId" @saved="onSkillSaved" />
  </div>
</template>

<script setup>
// 获取并排序 submissions
const rankedSubmissions = computed(() => {
  return submissions.value
    .filter(s => s.score !== null)
    .sort((a, b) => b.score - a.score)
})

function openSkillEditor(submission) {
  selectedSubmissionId.value = submission.id
  skillEditorRef.value.openDialog()
}
</script>
```

### 5.2 SkillEditor.vue 调整（支持多来源选择）

由于现在可能有多条邻居反馈，编辑器需要明确显示当前选中的是哪一个。

```vue
<template>
  <el-dialog v-model="showDialog" title="整理 Skill（基于选中的邻居反馈）" width="900px">
    <!-- 显示当前选中的邻居信息 -->
    <el-alert type="info" :closable="false">
      当前参考的反馈来源：{{ selectedNeighborName }} (评分: {{ selectedScore }}分)
    </el-alert>

    <!-- 邻居反馈内容（只读） -->
    <el-form-item label="邻居节点反馈内容">
      <el-input type="textarea" :value="neighborContent" readonly rows="5" />
    </el-form-item>

    <!-- 其余表单字段与之前相同... -->
  </el-dialog>
</template>
```

---

## 6. 后端 API 更新

### 6.1 触发评分接口

```python
@app.post("/bounties/{bounty_id}/evaluate-submissions")
async def evaluate_submissions(bounty_id: str):
    """对指定悬赏的所有未评分提交进行自动评分"""
    with get_db() as conn:
        bounty = conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
        if not bounty:
            raise HTTPException(404, "Bounty not found")

        submissions = conn.execute(
            "SELECT * FROM submissions WHERE bounty_id = ? AND score IS NULL",
            (bounty_id,)
        ).fetchall()

    evaluator = SubmissionEvaluator()
    for sub in submissions:
        score, reason = await evaluator.evaluate(dict(bounty), dict(sub))
        with get_db() as conn:
            conn.execute(
                "UPDATE submissions SET score = ?, score_reason = ? WHERE id = ?",
                (score, reason, sub["id"])
            )
    return {"evaluated": len(submissions)}
```

### 6.2 获取悬赏详情时包含评分

原 `/bounties/{id}` 接口返回的 `submissions` 列表需增加 `score` 和 `score_reason` 字段。

### 6.3 `/curate` 接口调整

无需大改，只需确保传入的 `submission_id` 合法即可（已在上一轮 Review 中强调过校验）。

---

## 7. 执行步骤更新

在原计划基础上增加：

5. **数据库迁移**：为 `submissions` 表添加 `score` 和 `score_reason` 列。
6. **实现自动评分模块**：创建 `evaluator.py`，封装 LLM 调用逻辑。
7. **添加评分触发逻辑**：可在悬赏关闭时自动触发，或由前端按钮手动触发。
8. **前端聚合视图开发**：在 `BountyMarket.vue` 中添加排行榜表格。

---

## 8. 预期效果更新

1. **悬赏详情页面新增“邻居反馈排行榜”**：
   - 自动显示每个邻居的评分、评分理由。
   - 发布者可一目了然地看出哪个邻居的回答质量最高。

2. **Skill 整理流程更智能**：
   - 用户点击“基于此项整理 Skill”后，编辑器自动填充该邻居的反馈内容。
   - 用户仍可自由修改 Skill 的名称、描述和使用方法。

3. **日志输出示例**：
```
[Evaluator] Bounty abc: 3 submissions evaluated.
[Evaluator] Sub def: score=92, reason="内容完整准确，可直接执行"
[Evaluator] Sub ghi: score=67, reason="部分逻辑错误，需人工修正"
```

---

## 9. 关键改动点总结

| 改动项 | 说明 |
|--------|------|
| **数据库** | submissions 表增加评分字段 |
| **新增模块** | `SubmissionEvaluator` 自动评分器 |
| **前端界面** | 增加邻居反馈排行榜表格，支持多选一整理 |
| **业务流程** | 增加“自动评分→用户选择最佳反馈→手动总结”环节 |

---

## 10. 附：自动评分可能的风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| LLM 评分不稳定 | 允许发布者手动覆盖评分（增加“重新评分”按钮） |
| 评分成本过高 | 对简单任务使用规则引擎，复杂任务才调用 LLM |
| 评分标准不透明 | 将评分理由与分数一并展示给用户 |

---

**结论**：该增强方案在保留原有人工总结 Skill 的灵活性的同时，利用自动评分大幅降低了发布者筛选高质量反馈的认知负担，尤其适用于多邻居协作场景。整体架构清晰，可落地性强。