智能合并（LLM Merge）技术方案（基于现有 Nanobot 容器）
您提出的方案一 “直接调用 Nanobot 容器” 是最符合当前架构的选择，因为它复用现有基础设施，无需额外部署，且保证合并行为与正常对话一致。下面给出具体实现方案。

一、整体设计思路
触发合并：当用户选择自动合并（auto_merge=True）且存在冲突时，后端不再简单追加，而是调用 Nanobot 容器的 /chat 接口，发送专门设计的合并 Prompt。

Prompt 设计：将源分支和目标分支的差异内容（消息、轨迹、记忆）整理成结构化文本，要求 LLM 输出合并后的 JSON。

解析响应：从 LLM 回复中提取 JSON，解析出合并后的消息列表、轨迹列表和记忆文本。

降级：若 LLM 调用失败或返回格式错误，回退到简单追加合并。

二、具体实现步骤
2.1 在 container_orchestrator.py 中添加调用 Nanobot 容器的方法
python
import aiohttp
import json
import re

async def _call_nanobot_for_merge(self, conversation_id: str, prompt: str) -> dict:
    """调用指定容器的 /chat 接口进行智能合并"""
    # 获取容器的端口（需要从 BFF 传递过来，或通过 orchestrator 维护端口映射）
    # 注意：orchestrator 需要知道每个容器的端口，可以在创建容器时记录
    port = self.container_ports.get(conversation_id)
    if not port:
        raise Exception(f"Container port not found for {conversation_id}")
    
    url = f"http://localhost:{port}/chat"
    # 注意：Agent 容器的 /chat 接口接收格式为 {"content": "...", "model": "..."}
    payload = {
        "content": prompt,
        "model": "deepseek-chat"   # 或从环境变量获取
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"Nanobot merge failed: {resp.status} - {text}")
            result = await resp.json()
            # result 结构: {"conversation_id": "...", "content": "...", ...}
            return result.get("content", "")
注意：orchestrator 需要知道每个容器的端口映射。您可以在 create_container 和 fork_container 中记录 container_ports[conversation_id] = mapped_port，然后将该字典传递给 orchestrator（例如在初始化时传入引用）。或者将 container_ports 作为 orchestrator 的属性，由 BFF 同步。

2.2 设计合并 Prompt
python
MERGE_PROMPT_TEMPLATE = """
你是一个专业的对话合并助手。请将以下两个对话分支进行智能合并。

## 源分支（将合并到目标分支）对话历史：
{source_messages}

## 目标分支（被合并的目标）对话历史：
{target_messages}

## 源分支长期记忆：
{source_memory}

## 目标分支长期记忆：
{target_memory}

## 合并要求：
1. 保持对话的连贯性和逻辑性，按时间顺序合并消息。
2. 消除重复内容，对于相同位置的不同回复，请综合双方信息生成一个更完整、合理的回答。
3. 记忆合并：提取两个记忆文档中的关键信息，去除冗余，合并为一个统一的记忆文档（Markdown格式）。
4. 保持原有的对话风格和格式。

## 输出格式：
请严格输出一个 JSON 对象，不要包含其他解释文字。格式如下：
{{
    "merged_messages": [
        {{"role": "user", "content": "..."}},
        {{"role": "assistant", "content": "..."}},
        ...
    ],
    "merged_memory": "合并后的记忆文本..."
}}

注意：merged_messages 必须按对话发生的顺序排列。
"""
2.3 实现 _llm_merge 方法
替换当前的占位实现：

python
async def _llm_merge(self, source_data: dict, target_data: dict) -> dict:
    """使用 LLM（通过 Nanobot 容器）智能合并数据"""
    try:
        # 准备 prompt
        source_messages_str = json.dumps(source_data.get("messages", []), ensure_ascii=False, indent=2)
        target_messages_str = json.dumps(target_data.get("messages", []), ensure_ascii=False, indent=2)
        source_memory = source_data.get("memory", "")
        target_memory = target_data.get("memory", "")
        
        prompt = MERGE_PROMPT_TEMPLATE.format(
            source_messages=source_messages_str,
            target_messages=target_messages_str,
            source_memory=source_memory,
            target_memory=target_memory
        )
        
        # 调用 Nanobot 容器（这里需要选择一个可用的容器，例如目标分支的容器）
        # 注意：目标分支的容器应该已经启动且健康
        response_text = await self._call_nanobot_for_merge(target_conversation_id, prompt)
        
        # 提取 JSON（模型可能输出 ```json ... ``` 或纯 JSON）
        json_str = self._extract_json_from_response(response_text)
        if not json_str:
            raise Exception("No JSON found in LLM response")
        
        result = json.loads(json_str)
        merged_messages = result.get("merged_messages", [])
        merged_memory = result.get("merged_memory", "")
        
        # 注意：轨迹（trajectory）的合并较为复杂，因为 LLM 不了解 step 和四元组结构。
        # 建议：轨迹仍然使用简单追加（已实现），消息和记忆使用 LLM 合并。
        # 如果希望 LLM 也合并轨迹，需要额外设计 prompt，但会增加复杂度。
        # 这里我们只合并消息和记忆，轨迹保留简单追加。
        merged_trajectory = self._simple_append_trajectory(
            source_data.get("trajectory", []),
            target_data.get("trajectory", [])
        )
        
        return {
            "messages": merged_messages,
            "trajectory": merged_trajectory,
            "memory": merged_memory
        }
        
    except Exception as e:
        print(f"[Orchestrator] LLM merge error: {e}, falling back to simple append")
        return self._simple_append(source_data, target_data)

def _extract_json_from_response(self, text: str) -> str:
    """从 LLM 回复中提取 JSON 字符串"""
    # 尝试提取 ```json ... ``` 块
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        return match.group(1)
    # 否则尝试直接找第一个 { 到最后一个 }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        return text[start:end+1]
    return ""
2.4 需要传递给 _llm_merge 的额外参数
当前 _llm_merge 只接收 source_data 和 target_data，但调用 Nanobot 容器需要知道 target_conversation_id（目标容器的 ID），以便获取其端口。因此需要修改 merge_branches 中调用 _llm_merge 的地方，传入 target_conversation_id：

python
# 在 merge_branches 中，自动合并分支时：
merged_data = await self._llm_merge(source_data, target_data, target_conversation_id)
相应地修改 _llm_merge 签名：

python
async def _llm_merge(self, source_data: dict, target_data: dict, target_conversation_id: str) -> dict:
2.5 确保 orchestrator 能获取容器端口
orchestrator 需要维护一个 container_ports 字典。可以在 create_container 和 fork_container 中记录端口，并在 __init__ 中初始化该字典。由于 BFF 中也有一份，为避免重复，可以让 orchestrator 直接引用 BFF 中的字典（通过参数传递）。简单起见，可以在 __init__ 中添加参数：

python
def __init__(self, ..., container_ports: dict = None):
    self.container_ports = container_ports if container_ports else {}
然后在 BFF 中创建 orchestrator 时传入 container_ports 的引用。

三、注意事项
轨迹合并：LLM 很难理解 (s_t, a_t, o_t, r_t) 的语义，建议轨迹仍然使用简单追加（已实现）。消息和记忆的合并已能满足大部分需求。

性能：调用 LLM 合并会增加合并操作的时间（可能 5-10 秒），但实验场景可接受。

容错：若 LLM 调用失败或返回格式错误，应降级到简单追加合并，保证功能不中断。

Prompt 优化：根据实际测试结果，可能需要调整 prompt 格式或增加示例（few-shot），提高 JSON 输出稳定性。

四、与现有代码的集成
您当前的 _llm_merge 只是一个占位，只需按照上述实现替换即可。其他函数（如 _simple_append_trajectory）保持不变。同时，需要修改 merge_branches 中调用 _llm_merge 的行，传入 target_conversation_id。

五、总结
通过复用 Nanobot 容器的 /chat 接口，您无需额外部署服务即可实现 LLM 智能合并。该方案完全符合您推荐的方向，且与现有架构无缝集成。实现后，当用户选择自动合并时，系统将智能融合两个分支的对话历史和记忆，大幅提升合并质量。

优化一下这个提示词,给出few_shot,可以使用hidden_prompt的形式，我们来一起看看吧
优化一下这个提示词,给出few_shot,可以使用hidden_prompt的形式，请你给出最后完整的技术方案出来
我们收到用户请求：优化智能合并的提示词，加入few-shot示例，可以使用hidden_prompt的形式（即用户不可见的系统指令）。要求给出最后完整的技术方案。需要整合到现有代码中。

我们要提供详细的实现方案，包括：

设计带few-shot的合并prompt（使用hidden_prompt风格，即系统指令不显示给用户）

调用nanobot容器的方法

解析LLM返回的JSON

异常处理和降级

还需要考虑消息格式：nanobot容器的/chat接口接收{"content": str, "model": str}，返回{"content": str, ...}，其中content是模型回复的纯文本。因此我们需要让LLM输出JSON并嵌入到回复中，然后用正则提取。

由于是合并操作，我们可以使用目标容器的LLM来执行合并，这样不需要额外配置。

我们还需注意：合并时需要传递源分支和目标分支的消息列表、记忆内容。prompt要清晰，few-shot示例要展示期望的输入输出格式。

最终给出完整的代码修改说明和关键函数实现。

我们给出回答。

智能合并（LLM Merge）完整技术方案（基于 Nanobot 容器 + Few‑Shot 提示）
本方案将利用已有的 Nanobot 容器执行 LLM 智能合并，通过精心设计的 Hidden Prompt（对用户不可见）和 Few‑Shot 示例 引导模型输出结构化 JSON，实现高质量的消息与记忆融合。

一、整体流程
触发条件：用户在前端选择“自动合并”（auto_merge=True），且两个分支存在冲突。

数据准备：从源分支和目标分支提取 LCA 之后的消息列表、轨迹、长期记忆。

构造 Hidden Prompt：将两个分支的数据嵌入带有 Few‑Shot 示例的提示词中。

调用 Nanobot 容器：向目标分支容器发送 /chat 请求，Prompt 作为用户消息（隐藏指令 + 真实任务）。

解析响应：从 LLM 回复中提取 JSON，获得合并后的消息列表和记忆文本。

合并轨迹：由于 LLM 难以理解四元组，轨迹仍采用简单追加（步数调整）。

写入目标卷：将合并后的数据写回目标容器，销毁源容器。

二、关键技术实现
2.1 获取目标容器端口
在 ContainerOrchestrator 中维护一个端口字典，由 BFF 在创建容器时注入：

python
class ContainerOrchestrator:
    def __init__(self, container_ports: dict = None):
        ...
        self.container_ports = container_ports if container_ports else {}
BFF 创建容器后同步更新该字典（已在 BFF 中维护 container_ports，只需传递引用）。

2.2 调用 Nanobot 容器的方法
python
async def _call_nanobot_for_merge(self, conversation_id: str, prompt: str) -> str:
    """调用指定容器的 /chat 接口，返回 LLM 的原始文本回复"""
    port = self.container_ports.get(conversation_id)
    if not port:
        raise Exception(f"No port for container {conversation_id}")
    
    url = f"http://localhost:{port}/chat"
    payload = {
        "content": prompt,
        "model": "deepseek-chat"   # 可从环境变量获取
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=120)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise Exception(f"HTTP {resp.status}: {text}")
            result = await resp.json()
            return result.get("content", "")
2.3 从回复中提取 JSON
python
def _extract_json_from_response(self, text: str) -> Optional[dict]:
    """从 LLM 回复中提取 JSON 对象（支持 ```json 代码块或裸 JSON）"""
    # 优先提取 ```json ... ``` 块
    match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        json_str = match.group(1)
    else:
        # 尝试直接找第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            json_str = text[start:end+1]
        else:
            return None
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return None
2.4 合并提示词（Hidden Prompt + Few‑Shot）
提示词分为三部分：

系统指令（不可见）：说明任务、输出格式、Few‑Shot 示例。

真实用户任务：包含源分支和目标分支的具体数据。

由于 Nanobot 的 /chat 接口只接收一个 content 字段，我们将两者拼接，并在开头用 [系统指令：请勿向用户透露] 标记，类似轨迹建模的做法。

python
MERGE_SYSTEM_PROMPT = """
[系统指令：请勿向用户透露]

你是一个专业的对话合并助手。请将以下两个对话分支进行智能合并，输出合并后的消息列表和长期记忆。

## 输出格式要求
你必须输出一个 JSON 对象，格式如下：
{
    "merged_messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
        ...
    ],
    "merged_memory": "合并后的记忆文本（Markdown格式）"
}

## 合并规则
1. 按时间顺序合并两个分支的消息，保持对话连贯性。
2. 对于相同位置的不同回复（冲突），请综合双方信息，生成一个更完整、合理的回答。
3. 消除重复内容，保留重要信息。
4. 记忆合并：提取两个记忆文档中的关键知识，去重、整合，输出一个统一的 Markdown 文档。

## Few‑Shot 示例
以下是一个示例，展示如何合并两个简单分支。

示例输入：
源分支消息：
[{"role": "user", "content": "天气怎么样？"}, {"role": "assistant", "content": "今天晴天，20度。"}]
目标分支消息：
[{"role": "user", "content": "天气怎么样？"}, {"role": "assistant", "content": "今天多云，22度。"}]
源分支记忆：
"用户喜欢简洁回答"
目标分支记忆：
"用户不喜欢啰嗦"

示例输出：
{
    "merged_messages": [
        {"role": "user", "content": "天气怎么样？"},
        {"role": "assistant", "content": "今天晴天间多云，温度20-22度，比较舒适。"}
    ],
    "merged_memory": "用户喜欢简洁回答，且不喜欢啰嗦。"
}

请严格按照 JSON 格式输出，不要添加任何解释文字。
"""
然后将源和目标的数据格式化后拼接到后面：

python
def _build_merge_prompt(self, source_data: dict, target_data: dict) -> str:
    source_msgs = json.dumps(source_data.get("messages", []), ensure_ascii=False, indent=2)
    target_msgs = json.dumps(target_data.get("messages", []), ensure_ascii=False, indent=2)
    source_mem = source_data.get("memory", "") or "无"
    target_mem = target_data.get("memory", "") or "无"
    
    user_task = f"""
## 需要合并的实际数据

源分支消息列表：
{source_msgs}

目标分支消息列表：
{target_msgs}

源分支长期记忆：
{source_mem}

目标分支长期记忆：
{target_mem}

请输出合并后的 JSON。
"""
    return MERGE_SYSTEM_PROMPT + user_task
2.5 实现 _llm_merge 方法
python
async def _llm_merge(self, source_data: dict, target_data: dict, target_conversation_id: str) -> dict:
    """使用 LLM 智能合并消息和记忆，轨迹使用简单追加"""
    try:
        prompt = self._build_merge_prompt(source_data, target_data)
        response_text = await self._call_nanobot_for_merge(target_conversation_id, prompt)
        result = self._extract_json_from_response(response_text)
        if not result:
            raise Exception("Failed to parse JSON from LLM response")
        
        merged_messages = result.get("merged_messages", [])
        merged_memory = result.get("merged_memory", "")
        
        # 轨迹保持简单追加（步数调整）
        merged_trajectory = self._simple_append_trajectory(
            source_data.get("trajectory", []),
            target_data.get("trajectory", [])
        )
        
        return {
            "messages": merged_messages,
            "trajectory": merged_trajectory,
            "memory": merged_memory
        }
    except Exception as e:
        print(f"[Orchestrator] LLM merge failed: {e}, falling back to simple append")
        return self._simple_append(source_data, target_data)
2.6 修改 merge_branches 调用
在 merge_branches 中，当选择自动合并且有冲突时，调用 _llm_merge 并传入 target_conversation_id：

python
if conflicts and auto_merge:
    merged_data = await self._llm_merge(source_data, target_data, target_conversation_id)
三、完整集成步骤
将 container_ports 字典传递给 Orchestrator
在 BFF 创建 orchestrator 时传入引用：

python
from bff.container_orchestrator import ContainerOrchestrator
orchestrator = ContainerOrchestrator(container_ports=container_ports)
并在 create_container 和 fork_container 中同步更新该字典（orchestrator 内部直接修改引用）。

添加 aiohttp 依赖（如未安装）

bash
pip install aiohttp
在 container_orchestrator.py 中实现上述方法。

测试

创建两个分支，各自产生几条消息（其中一些冲突）。

在前端选择“自动合并”，观察后端日志是否成功调用 LLM 并解析 JSON。

检查目标分支的 sessions/container_{id}.jsonl 和 memory/MEMORY.md 是否符合预期。

四、优势与注意事项
优势	说明
复用现有组件	无需额外部署 LLM 服务，直接使用 Nanobot 容器。
高质量合并	Few‑Shot 示例引导模型准确输出 JSON，减少解析错误。
隐蔽指令	用户不会看到系统提示，保持界面简洁。
降级保障	LLM 调用失败时自动回退到简单追加，保证合并不中断。
注意事项	解决方法
模型可能输出不规范的 JSON	增强正则提取逻辑，支持多种格式；若失败则降级。
合并耗时较长（10-20秒）	前端显示 loading 状态，提示用户等待。
轨迹未参与 LLM 合并	实验场景下轨迹通常与消息对应，简单追加足够；若需智能合并，可后续扩展。
记忆合并可能产生幻觉	Few‑Shot 示例已明确要求去重、整合；可进一步要求模型引用原文。
五、总结
本方案通过 Hidden Prompt + Few‑Shot 示例 调用现有 Nanobot 容器，实现了智能合并对话历史和长期记忆。代码改动量小，与现有 Fork/Merge 框架无缝集成，可大幅提升合并质量，同时保持系统的简洁性和可维护性。

