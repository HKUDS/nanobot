# 修复 bounty_hub.py 评分器空字典问题

## 问题描述

**严重程度**: 🔴 严重

**问题位置**: `bff/bounty_hub.py` 第 189 行

**问题代码**:
```python
# 使用 LLM 评分
score, reason = await evaluator.evaluate({}, sub)
```

**影响**:
- LLM 评分时无法获取悬赏描述（bounty description）
- 只能根据提交内容评分，无法对比任务要求
- 评分结果不准确、不专业

---

## 修复方案

### Step 1: 修改 `_auto_evaluate_submissions` 方法签名

**文件**: `bff/bounty_hub.py`

**修改内容**:
```python
# 原代码 (第 174 行):
async def _auto_evaluate_submissions(self, submissions: List[dict]) -> List[dict]:

# 修改为:
async def _auto_evaluate_submissions(self, bounty_id: str, submissions: List[dict]) -> List[dict]:
```

**理由**: 需要知道 bounty_id 才能获取悬赏详情

---

### Step 2: 在方法内获取 bounty 信息

**修改位置**: `_auto_evaluate_submissions` 方法内部

**添加代码** (在第 178 行之后):
```python
# 获取 bounty 详情用于评分
bounty = await self.get_bounty(bounty_id)
if not bounty:
    print(f"[BountyHub] [_auto_evaluate] 警告: 无法获取 bounty {bounty_id} 详情，使用空对象")
    bounty = {}
print(f"[BountyHub] [_auto_evaluate] bounty: {bounty.get('title', 'N/A')}")
```

---

### Step 3: 修改 evaluator.evaluate 调用

**修改位置**: 第 189 行

**原代码**:
```python
score, reason = await evaluator.evaluate({}, sub)
```

**修改为**:
```python
score, reason = await evaluator.evaluate(bounty, sub)
```

---

### Step 4: 修改调用处

**修改位置**: `close_bounty` 方法第 143 行

**原代码**:
```python
evaluation_results = await self._auto_evaluate_submissions(submissions)
```

**修改为**:
```python
evaluation_results = await self._auto_evaluate_submissions(bounty_id, submissions)
```

---

## 修改文件清单

| 文件 | 修改类型 | 修改内容 |
|------|----------|----------|
| `bff/bounty_hub.py` | 方法签名 | 添加 bounty_id 参数 |
| `bff/bounty_hub.py` | 方法体 | 获取 bounty 信息 |
| `bff/bounty_hub.py` | 调用处 | 传入 bounty_id |

---

## 验证方法

1. **代码检查**:
   - 确认 `_auto_evaluate_submissions(bounty_id, submissions)` 签名正确
   - 确认 `evaluator.evaluate(bounty, sub)` 传入真实 bounty 对象

2. **日志验证**:
   - 重启服务后，关闭悬赏时日志应显示：
   ```
   [BountyHub] [_auto_evaluate] bounty: xxx (悬赏标题)
   [Evaluator] 悬赏描述: xxx...
   ```

3. **功能验证**:
   - 发布悬赏 → 提交方案 → 关闭悬赏 → 检查评分理由是否包含"根据悬赏描述..."

---

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 回归风险 | 中 | 仅修改方法签名和调用方式 |
| 数据库访问 | 低 | 使用现有的 get_bounty 方法 |
| 并发问题 | 低 | 单线程调用，无并发问题 |

---

## 实施步骤

1. [ ] 修改 `_auto_evaluate_submissions` 方法签名
2. [ ] 在方法内添加获取 bounty 的代码
3. [ ] 修改 `evaluator.evaluate` 调用
4. [ ] 修改 `close_bounty` 中的调用处
5. [ ] 验证日志输出
6. [ ] 测试完整流程
