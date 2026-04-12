# Skill 持久化与前端展示技术方案

## 一、需求分析

### 1.1 当前问题
- 发布节点总结 Skill 后，数据存入数据库，但前端没有显示入口
- 没有将 Skill 文件导出到宿主机指定目录

### 1.2 目标
- 前端能够查看已沉淀的 Skill
- Skill 代码能够导出到宿主机目录

---

## 二、技术方案

### 2.1 后端改动

| 文件 | 改动内容 |
|------|----------|
| `shared/config.py` | 新增 `SKILL_EXPORT_DIR` 配置 |
| `bff/bounty_hub.py` | `_auto_curate_best_skill` 调用 `export_skill`，返回 `export_path` |
| `bff/public_space.py` | 确保 `export_skill` 方法返回导出路径 |
| `bff/bff_service.py` | 新增 `GET /public-skills/{skill_id}` 接口 |

### 2.2 前端改动

| 文件 | 改动内容 |
|------|----------|
| `frontend/src/components/BountyMarket.vue` | 结算报告中显示 Skill 沉淀信息，点击可查看详情 |
| `frontend/src/api/agentBff.js` | 添加 `getSkill` 方法 |

---

## 三、后端实现细节

### 3.1 配置导出目录

在 `shared/config.py` 中添加：

```python
SKILL_EXPORT_DIR = os.environ.get("SKILL_EXPORT_DIR", "/app/skills")
```

### 3.2 修改 `_auto_curate_best_skill`

在结算时调用 `export_skill` 并返回路径：

```python
async def _auto_curate_best_skill(self, bounty_id: str, evaluation_results: list, issuer_id: str) -> dict:
    # ... 现有逻辑 ...
    doc_id = await public_space.add_skill(...)

    # 导出到宿主机
    export_path = await public_space.export_skill(doc_id, f"{SKILL_EXPORT_DIR}/{doc_id}.py")

    return {
        "status": "success",
        "doc_id": doc_id,
        "submission_id": best["submission_id"],
        "score": best["score"],
        "export_path": export_path
    }
```

### 3.3 新增 API

```python
@app.get("/public-skills/{skill_id}")
async def get_skill(skill_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM public_knowledge WHERE id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Skill not found")
    skill = dict(row)
    return skill
```

---

## 四、前端实现细节

### 4.1 结算报告中显示 Skill

在 `BountyMarket.vue` 的结算报告弹窗中添加：

```vue
<div v-if="settlementReport.curation" class="curation-info">
  <el-alert type="success" :closable="false">
    <template #title>
      🎉 已自动沉淀 Skill：{{ settlementReport.curation.name || settlementReport.curation.doc_id }}
    </template>
    <el-button size="small" type="primary" @click="viewSkill(settlementReport.curation.doc_id)">
      查看详情
    </el-button>
  </el-alert>
</div>
```

### 4.2 Skill 详情弹窗

```javascript
async function viewSkill(skillId) {
  try {
    const res = await getSkill(skillId)
    currentSkill.value = res.data
    showSkillDialog.value = true
  } catch (e) {
    ElMessage.error('获取 Skill 失败')
  }
}
```

---

## 五、实施步骤

### Step 1: 后端基础配置
- [ ] 在 `shared/config.py` 添加 `SKILL_EXPORT_DIR`
- [ ] 确保导出目录存在

### Step 2: 后端逻辑修改
- [ ] 修改 `_auto_curate_best_skill` 调用 `export_skill`
- [ ] 修改 `PublicSpace.export_skill` 返回路径
- [ ] 新增 `GET /public-skills/{skill_id}` 接口

### Step 3: 前端实现
- [ ] 在 `agentBff.js` 添加 `getSkill` 方法
- [ ] 在结算报告弹窗中添加 Skill 展示
- [ ] 实现 Skill 详情查看弹窗

### Step 4: 测试验证
- [ ] 结算后 Skill 正确导出到宿主机目录
- [ ] 前端正确显示 Skill 沉淀信息
- [ ] Skill 详情弹窗正确展示内容

---

## 六、文件清单

| 文件路径 | 改动 |
|----------|------|
| `shared/config.py` | 新增配置 |
| `bff/bounty_hub.py` | 修改 `_auto_curate_best_skill` |
| `bff/public_space.py` | 修改 `export_skill` |
| `bff/bff_service.py` | 新增 API |
| `frontend/src/api/agentBff.js` | 新增 `getSkill` |
| `frontend/src/components/BountyMarket.vue` | 添加展示逻辑 |

---

## 七、风险与注意事项

1. 导出目录需要有写权限
2. Skill 详情弹窗可复用 `SkillEditor` 的展示逻辑
3. 确保 `curation_results` 在结算返回数据中正确传递
