# 悬赏任务结束优化计划

## 现状分析

### 当前实现
- `close_bounty` 方法：仅关闭悬赏任务，更新状态为 `completed`
- `evaluate_and_reward` 方法：评估方案并发放奖励（存在，但未被 `close_bounty` 调用）
- `curate_skill_to_public` 方法：整理 skill 到公共知识库（存在，但需手动调用）
- `update_edge_weights_after_bounty` 方法：更新边权（已实现）

### 问题
1. **无自动评级**：悬赏结束后没有自动对提交结果进行评级
2. **无自动奖励发放**：奖励不会在任务结束时自动发放
3. **无自动 Skill 沉淀**：优秀的 solution 不会自动整理到公共知识库
4. **无详细日志**：缺少任务结束流程的详细日志

---

## 优化方案

### 1. 修改 `close_bounty` 方法
**目标**：在任务结束时自动完成评级、奖励发放和 Skill 沉淀

**新增逻辑**：
1. 获取所有提交（submissions）
2. 如果有提交：
   - 对提交进行自动评级（根据内容质量）
   - 发放奖励给排名前 N 的提交者
   - 将排名第一的 solution 的 skill_code 沉淀到公共知识库
3. 如果没有提交：仅关闭任务
4. 更新边权

### 2. 增强评级逻辑
**自动评级标准**：
- 有 skill_code 且内容充实 → 高分
- 有 skill_code 但内容较少 → 中等
- 无 skill_code → 低分
- 评级结果写入 `evaluation_score` 字段

### 3. 奖励发放逻辑
**奖励分配规则**（沿用现有逻辑）：
- 第 1 名：50%
- 第 2 名：30%
- 第 3 名：20%

### 4. Skill 沉淀逻辑
**自动沉淀规则**：
- 找到评级最高的提交
- 如果该提交有 `skill_code`，自动调用 `curate_skill_to_public`
- 生成默认 tags：`["bounty", "auto-curated"]`

### 5. 添加详细日志
**日志级别**：
- `INFO`：主要流程节点
- `DEBUG`：详细信息
- `ERROR`：错误信息

---

## 技术实现

### 修改文件
- `bff/bounty_hub.py`

### 代码结构

```python
async def close_bounty(self, bounty_id: str, issuer_id: str) -> dict:
    """
    关闭悬赏任务
    返回结果包含：
    - status: 任务状态
    - evaluation_results: 评级结果
    - reward_results: 奖励发放结果
    - curation_results: Skill 沉淀结果
    """
    print(f"[BountyHub] ===== 开始关闭悬赏任务 =====")
    print(f"[BountyHub] bounty_id={bounty_id}, issuer={issuer_id}")
    
    # 1. 验证发布者身份
    print(f"[BountyHub] [Step 1] 验证发布者身份...")
    # ... 验证逻辑
    
    # 2. 获取所有提交
    print(f"[BountyHub] [Step 2] 获取所有提交...")
    submissions = await self.get_submissions(bounty_id)
    print(f"[BountyHub] 找到 {len(submissions)} 个提交")
    
    result = {
        "status": "completed",
        "submissions_count": len(submissions),
        "evaluation_results": [],
        "reward_results": [],
        "curation_results": None
    }
    
    if not submissions:
        print(f"[BountyHub] 没有提交，直接关闭任务")
    else:
        # 3. 自动评级
        print(f"[BountyHub] [Step 3] 开始自动评级...")
        evaluation_results = await self._auto_evaluate_submissions(submissions)
        result["evaluation_results"] = evaluation_results
        print(f"[BountyHub] 评级完成: {evaluation_results}")
        
        # 4. 发放奖励
        print(f"[BountyHub] [Step 4] 开始发放奖励...")
        reward_results = await self._distribute_rewards(bounty_id, evaluation_results)
        result["reward_results"] = reward_results
        print(f"[BountyHub] 奖励发放完成: {reward_results}")
        
        # 5. Skill 沉淀
        print(f"[BountyHub] [Step 5] 开始 Skill 沉淀...")
        curation_result = await self._auto_curate_best_skill(bounty_id, evaluation_results, issuer_id)
        result["curation_results"] = curation_result
        print(f"[BountyHub] Skill 沉淀完成: {curation_result}")
    
    # 6. 更新边权
    print(f"[BountyHub] [Step 6] 开始更新边权...")
    await self.update_edge_weights_after_bounty(issuer_id, bounty_id)
    print(f"[BountyHub] 边权更新完成")
    
    # 7. 更新任务状态
    print(f"[BountyHub] [Step 7] 更新任务状态为 completed...")
    with get_db() as conn:
        conn.execute("UPDATE bounties SET status = 'completed' WHERE id = ?", (bounty_id,))
    
    print(f"[BountyHub] ===== 悬赏任务关闭完成 =====")
    print(f"[BountyHub] 最终结果: {result}")
    
    return result


async def _auto_evaluate_submissions(self, submissions: List[dict]) -> List[dict]:
    """
    自动评级提交
    评级标准：
    - 有 skill_code 且内容充实(>100字符) → 0.9
    - 有 skill_code 但内容较少(≤100字符) → 0.7
    - 无 skill_code 但有内容(>50字符) → 0.5
    - 无有效内容 → 0.3
    """
    print(f"[BountyHub] [_auto_evaluate] 开始评级 {len(submissions)} 个提交...")
    
    evaluation_results = []
    for i, sub in enumerate(submissions):
        sub_id = sub["id"]
        content = sub.get("content", "") or ""
        skill_code = sub.get("skill_code") or ""
        
        print(f"[BountyHub] [_auto_evaluate] 提交 {i+1}: id={sub_id}")
        print(f"[BountyHub] [_auto_evaluate]   - 内容长度: {len(content)}")
        print(f"[BountyHub] [_auto_evaluate]   - skill_code: {'有' if skill_code else '无'}")
        
        # 计算分数
        if skill_code and len(content) > 100:
            score = 0.9
            level = "A"
        elif skill_code and len(content) > 0:
            score = 0.7
            level = "B"
        elif len(content) > 50:
            score = 0.5
            level = "C"
        else:
            score = 0.3
            level = "D"
        
        # 更新数据库
        with get_db() as conn:
            conn.execute("UPDATE submissions SET evaluation_score = ? WHERE id = ?", (score, sub_id))
        
        result = {
            "submission_id": sub_id,
            "agent_id": sub["agent_id"],
            "score": score,
            "level": level
        }
        evaluation_results.append(result)
        
        print(f"[BountyHub] [_auto_evaluate]   - 评分: {score} (等级: {level})")
    
    # 按分数排序
    evaluation_results.sort(key=lambda x: x["score"], reverse=True)
    print(f"[BountyHub] [_auto_evaluate] 评级完成，排名: {[r['submission_id'] for r in evaluation_results]}")
    
    return evaluation_results


async def _distribute_rewards(self, bounty_id: str, evaluation_results: List[dict]) -> dict:
    """
    发放奖励
    分配比例：第1名50%，第2名30%，第3名20%
    """
    print(f"[BountyHub] [_distribute] 开始发放奖励...")
    
    # 获取悬赏金额
    with get_db() as conn:
        row = conn.execute("SELECT reward_pool FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
        if not row:
            raise ValueError("Bounty not found")
        reward_pool = row["reward_pool"]
    
    print(f"[BountyHub] [_distribute] 奖励池: {reward_pool} Token")
    
    ratios = [0.5, 0.3, 0.2]
    reward_results = []
    
    for i, result in enumerate(evaluation_results[:3]):  # 只奖励前3名
        if i >= len(ratios):
            break
        
        sub_id = result["submission_id"]
        agent_id = result["agent_id"]
        ratio = ratios[i]
        amount = int(reward_pool * ratio)
        
        print(f"[BountyHub] [_distribute] 奖励 #{i+1}: agent={agent_id}, 比例={ratio}, 金额={amount}")
        
        # 发放奖励
        try:
            await self.wallet.transfer("system", agent_id, amount, "bounty_reward", bounty_id)
            result["reward_amount"] = amount
            result["status"] = "success"
            print(f"[BountyHub] [_distribute]   - 发放成功!")
        except Exception as e:
            result["reward_amount"] = 0
            result["status"] = "failed"
            result["error"] = str(e)
            print(f"[BountyHub] [_distribute]   - 发放失败: {e}")
        
        reward_results.append(result)
    
    print(f"[BountyHub] [_distribute] 奖励发放完成，共 {len(reward_results)} 人获得奖励")
    return reward_results


async def _auto_curate_best_skill(self, bounty_id: str, evaluation_results: List[dict], issuer_id: str) -> dict:
    """
    自动沉淀最佳 Skill 到公共知识库
    条件：排名第1且有 skill_code
    """
    print(f"[BountyHub] [_curate] 开始 Skill 沉淀...")
    
    if not evaluation_results:
        print(f"[BountyHub] [_curate] 没有评级结果，跳过 Skill 沉淀")
        return None
    
    best = evaluation_results[0]  # 得分最高的
    
    # 获取提交详情
    with get_db() as conn:
        sub_row = conn.execute("SELECT content, skill_code FROM submissions WHERE id = ?", 
                              (best["submission_id"],)).fetchone()
    
    if not sub_row or not sub_row["skill_code"]:
        print(f"[BountyHub] [_curate] 最佳提交没有 skill_code，跳过 Skill 沉淀")
        return None
    
    print(f"[BountyHub] [_curate] 最佳提交: {best['submission_id']}")
    print(f"[BountyHub] [_curate] Skill Code 长度: {len(sub_row['skill_code'])}")
    
    try:
        # 调用现有的 curate_skill_to_public
        doc_id = await self.curate_skill_to_public(
            bounty_id=bounty_id,
            submission_id=best["submission_id"],
            issuer_id=issuer_id,
            tags=["bounty", "auto-curated", f"score:{best['score']}"]
        )
        
        print(f"[BountyHub] [_curate] Skill 沉淀成功! doc_id={doc_id}")
        return {
            "status": "success",
            "doc_id": doc_id,
            "submission_id": best["submission_id"],
            "score": best["score"]
        }
    except Exception as e:
        print(f"[BountyHub] [_curate] Skill 沉淀失败: {e}")
        return {
            "status": "failed",
            "error": str(e)
        }
```

---

## 执行步骤

1. **读取现有代码**：确认 `close_bounty` 等方法的当前实现
2. **修改 `close_bounty` 方法**：
   - 添加详细日志
   - 添加自动评级调用
   - 添加奖励发放调用
   - 添加 Skill 沉淀调用
3. **添加辅助方法**：
   - `_auto_evaluate_submissions`：自动评级
   - `_distribute_rewards`：发放奖励
   - `_auto_curate_best_skill`：自动沉淀 Skill
4. **测试验证**：构建并测试

---

## 预期效果

### 日志输出示例
```
[BountyHub] ===== 开始关闭悬赏任务 =====
[BountyHub] bounty_id=xxx, issuer=yyy
[BountyHub] [Step 1] 验证发布者身份...
[BountyHub] [Step 2] 获取所有提交...
[BountyHub] 找到 3 个提交
[BountyHub] [Step 3] 开始自动评级...
[BountyHub] [_auto_evaluate] 提交 1: id=abc
[BountyHub] [_auto_evaluate]   - 内容长度: 500
[BountyHub] [_auto_evaluate]   - skill_code: 有
[BountyHub] [_auto_evaluate]   - 评分: 0.9 (等级: A)
...
[BountyHub] [Step 4] 开始发放奖励...
[BountyHub] [_distribute] 奖励池: 1000 Token
[BountyHub] [_distribute] 奖励 #1: agent=xxx, 比例=0.5, 金额=500
[BountyHub] [_distribute]   - 发放成功!
...
[BountyHub] [Step 5] 开始 Skill 沉淀...
[BountyHub] [_curate] Skill 沉淀成功! doc_id=zzz
[BountyHub] ===== 悬赏任务关闭完成 =====
```

### 返回值结构
```json
{
  "status": "completed",
  "submissions_count": 3,
  "evaluation_results": [
    {"submission_id": "abc", "agent_id": "xxx", "score": 0.9, "level": "A"},
    {"submission_id": "def", "agent_id": "yyy", "score": 0.7, "level": "B"},
    {"submission_id": "ghi", "agent_id": "zzz", "score": 0.5, "level": "C"}
  ],
  "reward_results": [
    {"submission_id": "abc", "agent_id": "xxx", "reward_amount": 500, "status": "success"},
    {"submission_id": "def", "agent_id": "yyy", "reward_amount": 300, "status": "success"},
    {"submission_id": "ghi", "agent_id": "zzz", "reward_amount": 200, "status": "success"}
  ],
  "curation_results": {
    "status": "success",
    "doc_id": "zzz",
    "submission_id": "abc",
    "score": 0.9
  }
}
```

---

## 风险评估

- **风险**：自动评级不够准确
- **缓解**：使用简单规则，后续可引入 AI 辅助评级

- **风险**：奖励发放失败（如余额不足）
- **缓解**：添加异常处理，单笔失败不影响其他奖励

- **风险**：Skill 沉淀失败（如数据库错误）
- **缓解**：记录错误但不影响整体流程
