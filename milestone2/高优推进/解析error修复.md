好的，已按您的要求将 **LLM 二次转换** 提升至第二优先级。以下是调整后的完整技术方案。

---

# 评分容错增强技术方案（优先级调整版）

## 一、降级策略（新顺序）

| 层级 | 策略 | 触发条件 |
|------|------|----------|
| 1 | 直接 JSON 解析 | LLM 返回标准 JSON |
| **2** | **调用 LLM 二次转换** | 直接解析失败，但原始响应非空 |
| 3 | 提取 Markdown 代码块 | LLM 二次转换失败，尝试提取 \`\`\`json 块 |
| 4 | 正则提取首个完整 JSON 对象 | 内容中嵌入了 JSON |
| 5 | 正则提取 score 和 reason 字段 | 返回纯文本评分描述 |
| 6 | 基于内容长度的规则评分 | 完全无法解析 |

**设计理由**：LLM 二次转换能最大程度保留语义判断的准确性，且仅当直接解析失败才调用，避免不必要的额外开销。

---

## 二、核心代码实现（调整后）

### 2.1 新增/修改的辅助函数

```python
import re
import json
from typing import Tuple, Optional

def extract_and_repair_json(text: str) -> Optional[dict]:
    """
    本地解析 JSON，包括提取 Markdown 代码块、完整 JSON 对象、正则提取字段。
    返回解析后的 dict，若失败则返回 None。
    """
    if not text:
        return None
    
    # 1. 直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    
    # 2. 提取 Markdown 代码块中的 JSON
    code_block_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    match = re.search(code_block_pattern, text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # 3. 提取首个完整 JSON 对象
    start = text.find('{')
    if start != -1:
        brace_count = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    try:
                        return json.loads(text[start:i+1])
                    except json.JSONDecodeError:
                        break
    
    # 4. 正则提取 score 和 reason
    score_match = re.search(r'(?:score|评分|分数)[\s:：]*(\d+(?:\.\d+)?)', text, re.IGNORECASE)
    reason_match = re.search(r'(?:reason|理由|原因)[\s:：]*(.+?)(?:\n|$)', text, re.IGNORECASE)
    if score_match:
        score = float(score_match.group(1))
        reason = reason_match.group(1).strip() if reason_match else "评分完成"
        return {"score": score, "reason": reason}
    
    return None


async def _convert_to_json_via_llm(raw_text: str) -> Optional[dict]:
    """
    调用 LLM 将纯文本转换为 JSON 格式。
    """
    global agent_loop
    if agent_loop is None:
        return None
    
    prompt = f"""请将以下评分内容转换为严格的 JSON 格式，只输出 JSON，不要包含其他文字。

评分内容：
{raw_text}

要求输出格式：
{{"score": 85, "reason": "内容完整准确，可直接执行"}}
"""
    try:
        from nanobot.bus.events import InboundMessage
        inbound_msg = InboundMessage(
            channel="container",
            chat_id=CONVERSATION_ID,
            sender_id="system",
            content=prompt,
            metadata={"type": "json_repair"}
        )
        response = await agent_loop._process_message(inbound_msg)
        raw_response = response.content if response else ""
        # 再次尝试本地提取（通常 LLM 会返回标准 JSON）
        return extract_and_repair_json(raw_response)
    except Exception as e:
        print(f"[JSON修复] LLM转换失败: {e}")
        return None


def _rule_based_score(content: str) -> Tuple[float, str]:
    length = len(content.strip())
    if length < 50:
        return 30.0, "内容过短"
    elif length < 200:
        return 50.0, "内容较短"
    elif length < 500:
        return 70.0, "内容适中"
    else:
        return 80.0, "内容丰富"
```

### 2.2 修改评分函数（体现新优先级）

```python
async def evaluate_single(bounty_desc: str, submission_content: str) -> Tuple[float, str]:
    prompt = f"""你是一个任务评审专家。请根据以下悬赏要求和提交内容进行评分（0-100分），并给出简短理由。

悬赏描述：{bounty_desc}
提交内容：{submission_content}

评分标准：
- 完整性（40%）：是否完全满足任务要求
- 准确性（30%）：内容是否正确、无错误
- 可执行性（30%）：是否可以直接使用或执行

请严格按以下 JSON 格式输出，不要包含任何其他内容：
{{"score": 85, "reason": "内容完整准确，可直接执行"}}
"""
    try:
        from nanobot.bus.events import InboundMessage
        inbound_msg = InboundMessage(
            channel="container",
            chat_id=CONVERSATION_ID,
            sender_id="system",
            content=prompt,
            metadata={"type": "evaluation"}
        )
        response = await agent_loop._process_message(inbound_msg)
        raw_response = response.content if response else ""
        print(f"[Evaluate] 原始响应: {raw_response[:200]}...")
        
        # ---------- 新优先级解析流程 ----------
        result = None
        
        # 层级1：直接解析
        try:
            result = json.loads(raw_response.strip())
            print("[Evaluate] 层级1：直接JSON解析成功")
        except json.JSONDecodeError:
            pass
        
        # 层级2：LLM二次转换（直接解析失败时立即调用）
        if result is None:
            print("[Evaluate] 层级1失败，层级2：调用LLM二次转换...")
            result = await _convert_to_json_via_llm(raw_response)
            if result:
                print("[Evaluate] 层级2：LLM转换成功")
        
        # 层级3~5：本地解析降级（调用 extract_and_repair_json）
        if result is None:
            print("[Evaluate] 层级2失败，尝试本地解析降级...")
            result = extract_and_repair_json(raw_response)
            if result:
                print("[Evaluate] 本地解析降级成功")
        
        # 最终降级：规则评分
        if result:
            score = float(result.get("score", 50))
            reason = str(result.get("reason", ""))
        else:
            print("[Evaluate] 所有解析均失败，使用规则评分")
            score, reason = _rule_based_score(submission_content)
        
        return score, reason
    except Exception as e:
        print(f"[Evaluate] 异常: {e}")
        return _rule_based_score(submission_content)
```

### 2.3 应用到 `/evaluate` 和 `/evaluate_batch` 中的单个评审

- `/evaluate` 端点直接调用 `evaluate_single`。
- 批量评审中循环调用 `evaluate_single` 即可。

---

## 三、日志示例（体现新优先级）

```
[Evaluate] 原始响应: 评分：85分，理由：内容完整准确...
[Evaluate] 层级1：直接JSON解析成功   # 或
[Evaluate] 层级1失败，层级2：调用LLM二次转换...
[Evaluate] 层级2：LLM转换成功         # 或
[Evaluate] 层级2失败，尝试本地解析降级...
[Evaluate] 本地解析降级成功           # 或
[Evaluate] 所有解析均失败，使用规则评分
```

---

## 四、实施步骤

1. 在 `agent_server.py` 中替换/新增上述函数。
2. 修改 `/evaluate` 和 `_evaluate_single` 的解析逻辑，严格按照新优先级。
3. 重新构建 Agent 镜像并部署。
4. 测试场景：故意构造非 JSON 响应（例如手动在测试容器中模拟），观察是否优先调用 LLM 二次转换。

---

## 五、说明

- **成本考虑**：LLM 二次转换仅在直接 JSON 解析失败时触发，正常情况下不会增加开销。
- **可靠性**：即使 LLM 二次转换失败，仍有后续多层本地降级保障评分流程不中断。
- **前端无感知**：无论走哪条路径，最终均输出标准 JSON，前端展示逻辑无需修改。