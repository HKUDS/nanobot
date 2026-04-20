"""
SAYG-Mem 对比实验 - LLM盲评模块

功能：
1. 读取PublicMemory文件
2. 创建评估Agent容器
3. 调用Agent进行质量评分（1-5分）
4. 返回平均分
"""

import os
import json
import re
import httpx
import asyncio
from typing import List, Dict

BFF_BASE_URL = os.environ.get("BFF_BASE_URL", "http://localhost:8000")


def read_public_memory(file_path: str) -> List[Dict]:
    """读取PublicMemory文件"""
    entries = []
    if not os.path.exists(file_path):
        print(f"[读取PublicMemory] 文件不存在: {file_path}")
        return entries
    
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue
    
    print(f"[读取PublicMemory] {file_path}: {len(entries)}条")
    return entries


async def create_evaluator_agent() -> Dict:
    """创建评估Agent容器（通过BFF创建新的conversation）"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{BFF_BASE_URL}/conversations",
                json={"title": "evaluator_agent", "model": "deepseek-chat"}
            )
            resp.raise_for_status()
            result = resp.json()
            conv_id = result.get("conversation_id")
            print(f"[创建评估Agent] 成功: {conv_id}")
            
            # 获取容器端口
            info_resp = await client.get(f"{BFF_BASE_URL}/conversations/{conv_id}")
            info_resp.raise_for_status()
            info = info_resp.json()
            container_port = info.get("container_port")
            
            return {
                "conversation_id": conv_id,
                "container_port": container_port
            }
    except Exception as e:
        print(f"[创建评估Agent] 失败: {e}")
        raise


async def call_agent_evaluate(agent_id: str, content: str) -> float:
    """调用 Agent 对内容进行质量评分"""
    # 获取评估 Agent 端口
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/conversations/{agent_id}")
        resp.raise_for_status()
        port = resp.json().get("container_port")
        if not port:
            print("[Agent 评分] 无法获取评估 Agent 端口")
            return 3.0

    prompt = f"""请对以下知识条目的质量进行评分（1-5 分），评分标准：

5 分：内容精炼、无冗余、观点深刻、结构清晰
4 分：内容较好、少量冗余、观点有价值
3 分：内容一般、有一定冗余、观点普通
2 分：内容较差、冗余明显、观点浅显
1 分：内容差、大量重复、无价值

请只输出一个数字（1-5），不要任何解释。

待评估内容：
{content[:5000]}

评分："""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/chat",
            json={"content": prompt, "model": "deepseek-chat"}
        )
        resp.raise_for_status()
        result = resp.json()
        response_content = result.get("content", "").strip()

        import re
        match = re.search(r'\b([1-5])\b', response_content)
        if match:
            return float(match.group(1))

        print(f"[Agent 评分] 无法解析评分：{response_content}")
        return 3.0


async def call_agent_compare_evaluate(agent_id: str, a_content: str, b_content: str) -> float:
    """调用 Agent 对比 A 组和 B 组内容进行评分（相对评分）"""
    # 获取评估 Agent 端口
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{BFF_BASE_URL}/conversations/{agent_id}")
        resp.raise_for_status()
        port = resp.json().get("container_port")
        if not port:
            print("[Agent 对比评分] 无法获取评估 Agent 端口")
            return 3.0

    prompt = f"""请对比以下两组知识条目的质量，以 A 组为基准评价 B 组的相对质量（1-5 分）：

评分标准（相对于 A 组）：
5 分：B 组质量明显优于 A 组（B 组更精炼、更深刻、冗余更少）
4 分：B 组质量略优于 A 组
3 分：B 组与 A 组质量相当
2 分：B 组质量略差于 A 组
1 分：B 组质量明显差于 A 组（B 组冗余更多、内容更差）

请只输出一个数字（1-5），不要任何解释。

【A 组内容】：
{a_content[:3000]}

【B 组内容】：
{b_content[:3000]}

B 组相对评分："""

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"http://localhost:{port}/chat",
            json={"content": prompt, "model": "deepseek-chat"}
        )
        resp.raise_for_status()
        result = resp.json()
        response_content = result.get("content", "").strip()

        import re
        match = re.search(r'\b([1-5])\b', response_content)
        if match:
            return float(match.group(1))

        print(f"[Agent 对比评分] 无法解析评分：{response_content}")
        return 3.0


async def close_evaluator_agent(agent_info: Dict):
    """关闭评估Agent容器"""
    conv_id = agent_info["conversation_id"]
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(f"{BFF_BASE_URL}/conversations/{conv_id}")
            resp.raise_for_status()
            print(f"[关闭评估Agent] 成功: {conv_id}")
    except Exception as e:
        print(f"[关闭评估Agent] 失败: {e}")


async def evaluate_public_memory(file_path: str, group_name: str) -> float:
    """评估 PublicMemory 质量（独立评分）"""
    print(f"\n[LLM 盲评] 开始评估{group_name}...")
    
    entries = read_public_memory(file_path)
    if not entries:
        print(f"[LLM 盲评] {group_name}无内容")
        return 0.0
    
    # 创建评估 Agent
    evaluator_info = await create_evaluator_agent()
    evaluator_id = evaluator_info["conversation_id"]
    
    try:
        # 如果条目数太多，采样评估（最多评估 10 条）
        if len(entries) > 10:
            import random
            random.seed(42)  # 固定种子保证可复现
            sampled_entries = random.sample(entries, 10)
            print(f"[LLM 盲评] {group_name}共{len(entries)}条，采样 10 条评估")
        else:
            sampled_entries = entries
            print(f"[LLM 盲评] {group_name}共{len(entries)}条，全部评估")
        
        # 逐条评分
        scores = []
        for i, entry in enumerate(sampled_entries):
            content = entry.get("content", "")
            if not content:
                # 尝试其他字段
                content = entry.get("page_content", "")
            
            if content:
                score = await call_agent_evaluate(evaluator_id, content)
                scores.append(score)
                print(f"  [{group_name}] 第{i+1}条评分：{score}")
                await asyncio.sleep(1)  # 避免请求过快
        
        if not scores:
            print(f"[LLM 盲评] {group_name}无有效内容")
            return 0.0
        
        avg_score = sum(scores) / len(scores)
        print(f"\n[LLM 盲评] {group_name}平均分：{avg_score:.1f}/5.0 ({len(scores)}条)")
        
        return avg_score
    finally:
        # 确保评估 Agent 被清理
        await close_evaluator_agent(evaluator_info)


async def compare_public_memory(a_file_path: str, b_file_path: str) -> tuple:
    """对比评估 A 组和 B 组（先独立评 A，再对比评 B）"""
    print(f"\n[LLM 对比盲评] 开始对比评估...")
    
    a_entries = read_public_memory(a_file_path)
    b_entries = read_public_memory(b_file_path)
    
    if not a_entries:
        print(f"[LLM 对比盲评] A 组无内容")
        return 0.0, 0.0
    if not b_entries:
        print(f"[LLM 对比盲评] B 组无内容")
        return 0.0, 0.0
    
    # 创建评估 Agent
    evaluator_info = await create_evaluator_agent()
    evaluator_id = evaluator_info["conversation_id"]
    
    try:
        # 采样策略：A 组独立评分（最多 10 条），B 组对比评分（最多 10 条）
        if len(a_entries) > 10:
            import random
            random.seed(42)
            a_sampled = random.sample(a_entries, 10)
            print(f"[LLM 对比盲评] A 组共{len(a_entries)}条，采样 10 条独立评分")
        else:
            a_sampled = a_entries
            print(f"[LLM 对比盲评] A 组共{len(a_entries)}条，全部独立评分")
        
        if len(b_entries) > 10:
            import random
            random.seed(42)
            b_sampled = random.sample(b_entries, 10)
            print(f"[LLM 对比盲评] B 组共{len(b_entries)}条，采样 10 条对比评分")
        else:
            b_sampled = b_entries
            print(f"[LLM 对比盲评] B 组共{len(b_entries)}条，全部对比评分")
        
        # Step 1: 独立评估 A 组
        print(f"\n[Step 1] 独立评估 A 组...")
        a_scores = []
        for i, entry in enumerate(a_sampled):
            content = entry.get("content", "") or entry.get("page_content", "")
            if content:
                score = await call_agent_evaluate(evaluator_id, content)
                a_scores.append(score)
                print(f"  [A 组] 第{i+1}条独立评分：{score}")
                await asyncio.sleep(1)
        
        a_avg = sum(a_scores) / len(a_scores) if a_scores else 0.0
        print(f"\n[Step 1 完成] A 组独立评分平均：{a_avg:.1f}/5.0")
        
        # Step 2: 对比评估 B 组（以 A 组为基准）
        print(f"\n[Step 2] 对比评估 B 组（以 A 组为基准）...")
        b_relative_scores = []
        
        # 将 A 组采样内容合并为参考文本
        a_ref_content = "\n\n".join([e.get("content", "") or e.get("page_content", "") for e in a_sampled[:3]])  # 取前 3 条作为参考
        
        for i, entry in enumerate(b_sampled):
            b_content = entry.get("content", "") or entry.get("page_content", "")
            if b_content:
                # 对比评分（1-5 分，相对于 A 组）
                relative_score = await call_agent_compare_evaluate(evaluator_id, a_ref_content, b_content)
                b_relative_scores.append(relative_score)
                print(f"  [B 组] 第{i+1}条对比评分：{relative_score} (相对 A 组)")
                await asyncio.sleep(1)
        
        # B 组绝对分数 = A 组平均分 × (B 组相对分 / 3)
        # 相对分 3 分表示相当，所以除以 3 作为系数
        b_avg_absolute = a_avg * (sum(b_relative_scores) / len(b_relative_scores) / 3.0) if b_relative_scores else 0.0
        
        print(f"\n[LLM 对比盲评] 完成:")
        print(f"  A 组独立评分：{a_avg:.1f}/5.0 ({len(a_scores)}条)")
        print(f"  B 组相对评分：{sum(b_relative_scores)/len(b_relative_scores):.1f}/5.0 ({len(b_relative_scores)}条，相对于 A 组)")
        print(f"  B 组绝对评分：{b_avg_absolute:.1f}/5.0")
        
        return a_avg, b_avg_absolute
    finally:
        # 确保评估 Agent 被清理
        await close_evaluator_agent(evaluator_info)


if __name__ == "__main__":
    async def main():
        # 测试用
        a_path = os.path.join(os.path.dirname(__file__), "data", "public_memory", "public_memory.jsonl")
        b_path = os.path.join(os.path.dirname(__file__), "experiment_data", "b_public_memory.jsonl")
        
        a_score = await evaluate_public_memory(a_path, "A组")
        b_score = await evaluate_public_memory(b_path, "B组")
        
        print(f"\n最终评分:")
        print(f"  A组: {a_score:.1f}/5.0")
        print(f"  B组: {b_score:.1f}/5.0")
    
    asyncio.run(main())
