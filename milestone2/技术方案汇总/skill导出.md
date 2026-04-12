# Skill 持久化与前端展示技术方案

## 一、需求分析

1. **发布节点总结 Skill 后，前端没有显示**：目前 Skill 存入数据库后，前端没有对应的查看入口。
2. **将 Skill 文件导出到宿主机指定目录**：便于用户直接访问生成的 Skill 代码或文档。

## 二、现状梳理

- 后端 `bounty_hub.close_bounty` 在结算时会调用 `_auto_curate_best_skill`，内部通过 `public_space.add_skill` 将 Skill 写入 `public_knowledge` 表。
- `PublicSpace` 已有 `export_skill` 方法，可将 Skill 代码导出为文件。
- 前端目前仅有 `SkillEditor` 用于手动整理 Skill，缺少自动沉淀 Skill 的展示。

## 三、解决方案概览

| 模块 | 改动 |
|------|------|
| 后端 | 在自动沉淀 Skill 时，调用 `export_skill` 写入宿主机目录；结算结果中返回 Skill 基本信息（ID、名称等） |
| 后端 API | 新增 `GET /public-skills/{skill_id}` 获取单个 Skill 详情 |
| 前端 | 在结算报告卡片中增加“查看沉淀 Skill”按钮，点击弹窗展示 Skill 内容，并提供下载/导出链接 |

## 四、后端实现细节

### 4.1 配置宿主机导出目录

在 `shared/config.py` 或环境变量中定义：

```python
SKILL_EXPORT_DIR = os.environ.get("SKILL_EXPORT_DIR", "/app/skills")
```

确保目录存在且有写权限。

### 4.2 修改 `_auto_curate_best_skill`，导出文件并返回 Skill 信息

```python
async def _auto_curate_best_skill(self, bounty_id: str, evaluation_results: List[dict], issuer_id: str) -> dict:
    # ... 现有逻辑 ...
    doc_id = await public_space.add_skill(...)
    
    # 导出到宿主机
    export_path = await public_space.export_skill(doc_id, f"{SKILL_EXPORT_DIR}/{doc_id}.py")
    
    return {
        "status": "success",
        "doc_id": doc_id,
        "submission_id": best["submission_id"],
        "score": best["score"],
        "export_path": export_path   # 新增
    }
```

### 4.3 修改 `PublicSpace.export_skill` 方法

当前 `export_skill` 已存在，只需确保返回导出路径。

```python
async def export_skill(self, doc_id: str, export_path: str) -> str:
    # 现有逻辑，成功后返回 export_path
```

### 4.4 新增获取单个 Skill 的 API

```python
@app.get("/public-skills/{skill_id}")
async def get_skill(skill_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM public_knowledge WHERE id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Skill not found")
    skill = dict(row)
    if isinstance(skill.get("tags"), str):
        skill["tags"] = json.loads(skill["tags"])
    return skill
```

## 五、前端实现细节

### 5.1 修改结算报告数据结构

在 `BountyMarket.vue` 的 `closeBounty` 中接收 `curation_results`：

```javascript
settlementReport.value = {
  ...res.data,
  reward_pool: bounty.reward_pool,
  curation: res.data.curation_results   // { doc_id, export_path, ... }
}
```

### 5.2 在结算报告卡片中添加 Skill 展示区

```vue
<div v-if="settlementReport.curation" class="curation-info">
  <el-alert type="success" :closable="false">
    <template #title>
      🎉 已自动沉淀共识 Skill：{{ settlementReport.curation.doc_id }}
    </template>
    <el-button size="small" type="primary" @click="viewSkill(settlementReport.curation.doc_id)">
      查看 Skill 详情
    </el-button>
  </el-alert>
</div>
```

### 5.3 实现查看 Skill 弹窗

复用或新建一个简易的 Skill 详情弹窗，展示名称、能力描述、使用方法、Skill 代码。

```javascript
async function viewSkill(skillId) {
  try {
    const res = await request.get(`/public-skills/${skillId}`)
    currentSkill.value = res.data
    showSkillDialog.value = true
  } catch (e) {
    ElMessage.error('获取 Skill 失败')
  }
}
```

弹窗模板参考 `SkillEditor` 中的预览部分。

### 5.4 提供下载/导出链接（可选）

若后端返回了 `export_path`，可生成文件下载链接（需后端提供静态文件服务或将文件映射到前端可访问路径）。简单起见，可先仅展示内容，不提供直接下载。

## 六、测试验证步骤

1. 启动服务，确保 `SKILL_EXPORT_DIR` 目录存在且可写。
2. 运行完整悬赏流程（包含有 `skill_code` 的提交，或手动在提交中加入 skill_code 以便触发自动沉淀）。
3. 关闭悬赏后，检查：
   - 宿主机目录下是否生成了对应的 `.py` 文件。
   - 前端结算报告卡片是否显示“已自动沉淀 Skill”。
   - 点击查看 Skill 弹窗是否正确展示内容。
4. 对于没有 skill_code 的提交，确认结算报告不显示 Skill 沉淀信息。

## 七、文件清单与改动汇总

| 文件 | 改动 |
|------|------|
| `shared/config.py` | 新增 `SKILL_EXPORT_DIR` 配置 |
| `bff/bounty_hub.py` | `_auto_curate_best_skill` 返回 `export_path`；调用 `export_skill` |
| `bff/public_space.py` | 确保 `export_skill` 返回路径 |
| `bff/bff_service.py` | 新增 `GET /public-skills/{skill_id}` 接口 |
| `frontend/src/components/BountyMarket.vue` | 添加结算报告中的 Skill 展示区块、弹窗逻辑 |
| `frontend/src/api/agentBff.js` | 添加 `getSkill` 方法 |

## 八、附加说明

- 若希望手动整理的 Skill 也导出文件，可在 `api_curate_skill` 中调用同样的导出逻辑。
- 宿主机目录可通过 Docker 卷映射供用户直接访问。

此方案改动量适中，完整覆盖了 Skill 的文件导出与前端展示需求。