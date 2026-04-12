import uuid
import json
import numpy as np
import aiohttp
from datetime import datetime
from typing import List, Optional, Dict, Any
from bff.db import get_db
from bff.deepseek_embedding import DeepSeekEmbedding


class PublicSpace:
    def __init__(self):
        self.embedder = DeepSeekEmbedding()

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        v1 = np.array(vec1)
        v2 = np.array(vec2)
        return np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2))

    async def search(self, query: str, top_k: int = 5) -> List[dict]:
        query_vec = await self.embedder.embed_text(query)
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM public_knowledge").fetchall()
        scored = []
        for row in rows:
            row_dict = dict(row)
            if row_dict.get("embedding"):
                emb = json.loads(row_dict["embedding"])
                sim = self._cosine_similarity(query_vec, emb)
                row_dict["similarity"] = float(sim)
                scored.append((sim, row_dict))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, doc in scored[:top_k]:
            if isinstance(doc.get("tags"), str):
                doc["tags"] = json.loads(doc["tags"])
            results.append(doc)
        return results

    async def upload(self, title: str, content: str, skill_code: str, tags: List[str], author_id: str, knowledge_type: str = "skill") -> str:
        doc_id = str(uuid.uuid4())
        tags_json = json.dumps(tags)
        text_to_embed = f"{title}\n{content}\n{skill_code if skill_code else ''}"
        embedding = await self.embedder.embed_text(text_to_embed)
        embedding_json = json.dumps(embedding)
        with get_db() as conn:
            conn.execute("""
                INSERT INTO public_knowledge (id, type, title, content, skill_code, usage, tags, embedding, author_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, knowledge_type, title, content, skill_code, "", tags_json, embedding_json, author_id, datetime.now()))
        return doc_id

    async def increment_usage(self, doc_id: str):
        with get_db() as conn:
            conn.execute("UPDATE public_knowledge SET usage_count = usage_count + 1 WHERE id = ?", (doc_id,))

    async def export_skill_as_markdown(self, skill_id: str, export_dir: str) -> str:
        """
        将 Skill 导出为符合 Agent Skills 标准的 SKILL.md 文件。
        返回导出路径。
        """
        import os
        import re

        print(f"[PublicSpace] export_skill_as_markdown 被调用:")
        print(f"  - skill_id: {skill_id}")
        print(f"  - export_dir: {export_dir}")

        with get_db() as conn:
            row = conn.execute(
                "SELECT title, content, skill_code, usage FROM public_knowledge WHERE id = ?",
                (skill_id,)
            ).fetchone()
        
        if not row:
            print(f"[PublicSpace] ❌ Skill 不存在: skill_id={skill_id}")
            raise ValueError("Skill not found")
        
        print(f"[PublicSpace] 找到 Skill:")
        print(f"  - title: {row['title']}")
        print(f"  - content 长度: {len(row['content']) if row['content'] else 0}")
        print(f"  - skill_code 长度: {len(row['skill_code']) if row['skill_code'] else 0}")
        print(f"  - usage: '{row['usage']}'")

        name = row["title"]
        content = row["content"] or ""
        usage = row["usage"] or ""
        skill_code = row["skill_code"] or ""
        
        # 从 content 中提取 description（第一段非标题文本）
        description = ""
        lines = content.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('##'):
                description = line[:200]  # 取前200字符作为描述
                break
        
        if not description:
            description = f"技能: {name}"
        
        # 清理 description 中的特殊字符（YAML 安全）
        description_clean = description.replace('"', "'").replace('\n', ' ').replace('\r', '')
        
        # 创建技能文件夹（添加 UUID 避免名称冲突）
        import uuid
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower())
        folder_name = f"{safe_name}_{str(uuid.uuid4())[:8]}"
        skill_folder = os.path.join(export_dir, folder_name)
        os.makedirs(skill_folder, exist_ok=True)

        # 生成符合 Agent Skills 标准的 SKILL.md
        skill_md_content = f"""---
name: {name}
description: {description_clean}
---

# {name}

## 何时使用
{usage if usage else '当需要执行与此技能相关的任务时'}

## 技能内容
{content}

"""
        
        # 如果有代码，添加代码示例部分
        if skill_code:
            skill_md_content += f"""## 代码示例

```python
{skill_code}
```
"""
        
        skill_md_path = os.path.join(skill_folder, "SKILL.md")
        with open(skill_md_path, "w", encoding="utf-8") as f:
            f.write(skill_md_content)

        # 可选：如果 skill_code 非空，也保存为 skill.py
        if skill_code:
            code_path = os.path.join(skill_folder, "skill.py")
            with open(code_path, "w", encoding="utf-8") as f:
                f.write(skill_code)

        print(f"[PublicSpace] ✅ Skill 导出到：{skill_folder}")
        return skill_md_path  # 返回完整的 SKILL.md 文件路径

    async def add_skill(self, name: str, capability: str, usage: str = None,
                        source_submission_id: str = None, author_id: str = None) -> str:
        """添加 skill 到公共知识库"""
        print(f"[PublicSpace] 添加 skill: name={name}, source_submission_id={source_submission_id}")
        doc_id = str(uuid.uuid4())
        tags = ["skill", "manual-curated", "neighbor-source"]
        tags_json = json.dumps(tags)

        with get_db() as conn:
            conn.execute("""
                INSERT INTO public_knowledge
                (id, type, title, content, skill_code, usage, tags, author_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (doc_id, "skill", name, capability, "", usage or "",
                  tags_json, author_id, datetime.now()))

        print(f"[PublicSpace] Skill 保存成功：doc_id={doc_id}")
        return doc_id

    async def add_knowledge(self, knowledge_type: str = "skill", title: str = None,
                            content: str = None, skill_code: str = None,
                            usage: str = None, tags: list = None, author_id: str = None) -> str:
        """添加知识到公共知识库"""
        print(f"[PublicSpace] add_knowledge 被调用:")
        print(f"  - knowledge_type: {knowledge_type}")
        print(f"  - title: {title}")
        print(f"  - content 长度: {len(content) if content else 0}")
        print(f"  - skill_code 长度: {len(skill_code) if skill_code else 0}")
        print(f"  - usage: '{usage}'")
        print(f"  - tags: {tags}")
        
        doc_id = str(uuid.uuid4())
        tags_json = json.dumps(tags or [])
        text_to_embed = f"{title or ''}\n{content or ''}\n{skill_code or ''}"
        
        try:
            embedding = await self.embedder.embed_text(text_to_embed)
            embedding_json = json.dumps(embedding)
        except Exception as e:
            print(f"[PublicSpace] 嵌入生成失败，使用空嵌入: {e}")
            embedding_json = "[]"
        
        try:
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO public_knowledge
                    (id, type, title, content, skill_code, usage, tags, embedding, author_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (doc_id, knowledge_type, title, content, skill_code or "",
                      usage or "", tags_json, embedding_json, author_id, datetime.now()))
            print(f"[PublicSpace] ✅ 知识保存成功：doc_id={doc_id}")
            return doc_id
        except Exception as e:
            print(f"[PublicSpace] ❌ 知识保存失败: {e}")
            import traceback
            traceback.print_exc()
            raise

    def _get_proxy_connector(self):
        """获取代理连接器，如果配置了代理则使用代理"""
        import os
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        
        if https_proxy:
            print(f"[PublicSpace] 使用代理: {https_proxy}")
            import aiohttp
            # 使用 ProxyConnector 而不是 TCPConnector
            return aiohttp.ProxyConnector.from_url(https_proxy, ssl=False)
        
        return None

    async def summarize_submission_to_skill(self, submission_content: str, bounty_description: str = "") -> Dict[str, Any]:
        """
        使用 LLM 总结提交内容，生成标准化的 Skill 信息
        返回包含 name, description, usage, instructions 等字段的字典
        """
        print(f"[PublicSpace] 开始总结 Skill，内容长度: {len(submission_content)}")
        
        # 导入配置
        from shared.config import DEEPSEEK_API_KEY
        
        # 构建提示词
        # 注意：对于综合报告，submission_content 可能很长（已限制到20000），这里也相应增大到15000
        prompt = f"""你是一个 Skill 总结专家。请根据以下悬赏任务和提交内容，总结出一个可复用的 Agent Skill。

悬赏任务描述: {bounty_description[:500] if bounty_description else "未提供"}

提交内容: {submission_content[:15000]}

请将这个提交总结成一个标准化的 Agent Skill，包含以下部分：

1. **Skill 名称** (name): 简洁描述技能的核心功能，使用小写字母和连字符
2. **技能描述** (description): 1-2句话说明这个技能是什么，何时使用
3. **使用方法** (usage): 具体的使用步骤和指导
4. **核心指令** (instructions): 详细的执行步骤
5. **示例** (examples): 输入输出示例
6. **代码模板** (code_template): 可选的代码模板或示例

请以 JSON 格式输出，结构如下：
{{
    "name": "skill-name",
    "description": "技能描述",
    "usage": "使用步骤...",
    "instructions": "详细指令...", 
    "examples": "示例说明...",
    "code_template": "代码模板..."
}}

只输出 JSON，不要包含其他内容。"""

        # 调用 LLM API
        api_key = DEEPSEEK_API_KEY
        api_url = "https://api.deepseek.com/v1/chat/completions"
        
        if not api_key:
            print("[PublicSpace] ❌ 未配置 DEEPSEEK_API_KEY，无法总结 Skill")
            return self._create_fallback_skill(submission_content, bounty_description)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 1500
        }
        
        try:
            connector = self._get_proxy_connector()
            timeout = aiohttp.ClientTimeout(total=300)  # 增大到300秒，适应复杂综合报告
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.post(api_url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        print(f"[PublicSpace] LLM API 返回错误: {resp.status}, {error_text}")
                        return self._create_fallback_skill(submission_content, bounty_description)
                    
                    data = await resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # 解析 JSON 响应
                    try:
                        import re
                        json_str = content.strip()
                        # 提取 JSON 部分（可能包含代码块）
                        if "```json" in json_str:
                            json_str = re.search(r'```json\s*(.*?)\s*```', json_str, re.DOTALL)
                            json_str = json_str.group(1) if json_str else content
                        elif "```" in json_str:
                            json_str = re.search(r'```\s*(.*?)\s*```', json_str, re.DOTALL)
                            json_str = json_str.group(1) if json_str else content
                        
                        skill_data = json.loads(json_str)
                        print(f"[PublicSpace] ✅ Skill 总结成功: {skill_data.get('name', 'unknown')}")
                        return skill_data
                        
                    except Exception as e:
                        print(f"[PublicSpace] ❌ 解析 LLM 响应失败: {e}, 内容: {content[:200]}")
                        return self._create_fallback_skill(submission_content, bounty_description)
                        
        except Exception as e:
            print(f"[PublicSpace] ❌ LLM 调用失败: {e}")
            return self._create_fallback_skill(submission_content, bounty_description)

    def _create_fallback_skill(self, submission_content: str, bounty_description: str) -> Dict[str, Any]:
        """创建降级版本的 Skill（当 LLM 调用失败时）"""
        from datetime import datetime
        name = f"skill-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        
        return {
            "name": name,
            "description": f"基于悬赏任务生成的技能: {bounty_description[:100] if bounty_description else '未命名'}",
            "usage": "请参考提交内容中的具体实现",
            "instructions": f"这是一个基于以下内容生成的技能:\n\n{submission_content[:1000]}",
            "examples": "暂无示例",
            "code_template": ""
        }

    async def list_skills(self) -> List[dict]:
        """列出所有 skill"""
        print(f"[PublicSpace] 列出所有 skill")
        with get_db() as conn:
            rows = conn.execute("""
                SELECT * FROM public_knowledge WHERE type = 'skill'
                ORDER BY created_at DESC
            """).fetchall()

        skills = []
        for row in rows:
            skill = dict(row)
            if isinstance(skill.get("tags"), str):
                skill["tags"] = json.loads(skill["tags"])
            skills.append(skill)

        print(f"[PublicSpace] 找到 {len(skills)} 个 skill")
        return skills
