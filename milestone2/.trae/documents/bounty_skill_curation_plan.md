# 悬赏任务完整流程审查与实现计划

## 现状分析

### 已实现功能
1. **发布悬赏**：`create_bounty` 函数，支持设置标题、描述、奖励金额、Docker奖励
2. **结束任务**：`close_bounty` 函数，只有发布者可以操作
3. **分配奖励**：`evaluate_and_reward` 函数，支持多获胜者按比例分配奖励
4. **提交方案**：`submit_solution` 函数，支持提交内容和skill代码

### 缺失功能
1. **Skill整理到公共区域**：没有将获胜方案中的skill整理到公共知识库的功能
2. **Skill存储位置**：没有明确的skill存储策略

## 问题分析

### 核心问题
1. **Skill整理流程缺失**：悬赏结束后，发布者无法将优秀的skill整理到公共区域
2. **Skill存储位置不明确**：当前skill代码存储在 `submissions` 表中，但没有转移到公共知识库的机制
3. **公共知识库集成**：需要与现有的 `public_space` 模块集成

## 实现方案

### 方案 1：自动整理到公共知识库
- **触发时机**：悬赏结束并分配奖励后
- **实现方式**：在 `evaluate_and_reward` 函数中添加skill整理逻辑
- **存储位置**：使用现有的 `public_space` 模块，存储到 `public_knowledge` 表

### 方案 2：手动整理到公共知识库
- **触发时机**：发布者手动操作
- **实现方式**：添加新的API接口，允许发布者选择优秀skill进行整理
- **存储位置**：使用现有的 `public_space` 模块，存储到 `public_knowledge` 表

### 方案 3：支持外部存储
- **触发时机**：根据配置决定
- **实现方式**：添加配置选项，支持将skill存储到外部文件系统或代码仓库
- **存储位置**：可配置为本地文件系统、Git仓库或其他外部存储

## 推荐方案

**方案 2 + 方案 3**：手动整理 + 支持外部存储
- **优势**：灵活性高，发布者可以选择最优秀的skill进行整理，同时支持外部存储
- **劣势**：需要额外的用户操作
- **适用**：符合用户需求，支持将skill存储在docker外部

## 实现步骤

### 步骤 1：增强 BountyHub 模块
- **文件**：`bff/bounty_hub.py`
- **修改**：添加 `curate_skill_to_public` 方法，支持将skill整理到公共知识库

### 步骤 2：添加 API 接口
- **文件**：`bff/bff_service.py`
- **修改**：添加 `POST /bounties/{id}/curate-skill` 接口，允许发布者手动整理skill

### 步骤 3：支持外部存储
- **文件**：`bff/public_space.py`
- **修改**：添加 `export_skill` 方法，支持将skill导出到外部存储

### 步骤 4：前端界面增强
- **文件**：`frontend/src/components/BountyMarket.vue`
- **修改**：为已结束的悬赏添加"整理Skill"按钮

### 步骤 5：配置管理
- **文件**：`bff/config.py`（新建）
- **修改**：添加skill存储配置选项

## 技术实现

### 后端实现

1. **BountyHub 增强**：
   ```python
   async def curate_skill_to_public(self, bounty_id: str, submission_id: str, issuer_id: str, tags: List[str] = None) -> str:
       """将优秀的skill整理到公共知识库"""
       # 验证发布者身份
       with get_db() as conn:
           bounty_row = conn.execute("SELECT issuer_id FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
           if not bounty_row or bounty_row["issuer_id"] != issuer_id:
               raise ValueError("Only issuer can curate skill")
           
           # 获取submission信息
           sub_row = conn.execute("SELECT content, skill_code FROM submissions WHERE id = ?", (submission_id,)).fetchone()
           if not sub_row or not sub_row["skill_code"]:
               raise ValueError("No skill code found in submission")
       
       # 整理到公共知识库
       from bff.public_space import PublicSpace
       public_space = PublicSpace()
       doc_id = await public_space.add_knowledge(
           knowledge_type="skill",
           title=f"Skill from bounty: {bounty_id}",
           content=sub_row["content"],
           skill_code=sub_row["skill_code"],
           tags=tags or [],
           author_id=issuer_id
       )
       
       return doc_id
   ```

2. **API 接口**：
   ```python
   @app.post("/bounties/{bounty_id}/curate-skill")
   async def api_curate_skill(bounty_id: str, submission_id: str, issuer_id: str, tags: List[str] = None):
       try:
           doc_id = await bounty_hub.curate_skill_to_public(bounty_id, submission_id, issuer_id, tags)
           return {"status": "ok", "doc_id": doc_id}
       except ValueError as e:
           raise HTTPException(status_code=400, detail=str(e))
       except Exception as e:
           raise HTTPException(status_code=500, detail=f"Failed to curate skill: {str(e)}")
   ```

3. **外部存储支持**：
   ```python
   async def export_skill(self, doc_id: str, export_path: str) -> bool:
       """将skill导出到外部存储"""
       with get_db() as conn:
           row = conn.execute("SELECT title, content, skill_code FROM public_knowledge WHERE id = ?", (doc_id,)).fetchone()
           if not row:
               return False
       
       # 确保目录存在
       os.makedirs(os.path.dirname(export_path), exist_ok=True)
       
       # 导出为Python文件
       skill_content = f""""""
   # {row["title"]}
   # Exported from public knowledge
   
   {row["skill_code"]}
   """
       with open(export_path, "w", encoding="utf-8") as f:
           f.write(skill_content)
       
       return True
   ```

### 前端实现

1. **添加整理Skill按钮**：
   - 在已结束的悬赏详情中添加"整理Skill"按钮
   - 点击后显示提交列表，选择要整理的skill
   - 支持添加标签和描述

2. **API调用**：
   - 调用 `POST /bounties/{id}/curate-skill` 接口
   - 显示操作结果

## 配置管理

### 配置选项
```python
# bff/config.py
class Config:
    # Skill存储配置
    SKILL_STORAGE_TYPE = "database"  # database, filesystem, git
    SKILL_STORAGE_PATH = "/app/skills"  # 外部存储路径
    SKILL_EXPORT_ENABLED = True  # 是否启用外部导出
```

## 测试验证

### 测试流程
1. **发布悬赏**：创建一个包含skill需求的悬赏
2. **提交方案**：提交包含skill代码的方案
3. **结束任务**：发布者结束任务
4. **分配奖励**：为获胜方案分配奖励
5. **整理Skill**：发布者将优秀skill整理到公共区域
6. **验证存储**：检查skill是否正确存储到公共知识库
7. **测试外部存储**：如果配置了外部存储，验证skill是否导出到指定位置

### 预期结果
- **功能正常**：所有步骤都能正常执行
- **数据一致性**：skill正确存储到公共知识库
- **外部存储**：如果配置了外部存储，skill能正确导出
- **用户体验**：前端界面操作流畅

## 风险评估

- **风险**：外部存储权限问题
- **缓解**：添加权限检查，确保存储路径可写

- **风险**：skill代码质量问题
- **缓解**：添加代码验证和审核机制

- **风险**：存储路径配置错误
- **缓解**：添加配置验证和默认值

## 执行计划

1. **增强 BountyHub 模块**：添加 `curate_skill_to_public` 方法
2. **添加 API 接口**：实现 `POST /bounties/{id}/curate-skill` 接口
3. **支持外部存储**：在 `public_space.py` 中添加 `export_skill` 方法
4. **前端界面增强**：添加整理Skill功能
5. **配置管理**：添加skill存储配置选项
6. **测试验证**：执行完整测试流程
7. **文档更新**：更新相关文档