import uuid
import os
import json
import shutil
import tempfile
import aiohttp
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from bff.db import get_db
from bff.token_wallet import TokenWallet
from bff.node_relation import NodeRelationManager
from bff.evaluator import SubmissionEvaluator
from shared.config import SKILL_EXPORT_DIR, XUANSHANG_REPORT_DIR, DEEPSEEK_API_KEY


def extract_json(text: str) -> str:
    """从文本中提取完整的 JSON 对象（支持嵌套），处理 markdown 代码块"""
    json_str = text.strip()

    # 尝试提取 ```json ... ``` 代码块
    parts = json_str.split("```")
    for part in parts:
        part = part.strip()
        if part.startswith("json"):
            part = part[4:].strip()
        if part.startswith("{") and part.endswith("}"):
            json_str = part
            break

    # 提取 JSON（使用 brace-counting 算法支持嵌套）
    start = json_str.find('{')
    if start != -1:
        brace_count = 0
        end_pos = -1
        for i in range(start, len(json_str)):
            if json_str[i] == '{':
                brace_count += 1
            elif json_str[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_pos = i + 1
                    break
        if end_pos > 0:
            json_str = json_str[start:end_pos]

    return json_str

AGGREGATED_REPORT_PROMPT = """
你是一个知识提炼专家。请分析以下多个高质量提交内容，提炼出一份**标准化的 Agent Skill**。

悬赏任务描述：{bounty_description}

提交数量：{submission_count}
平均分数：{avg_score:.1f}

各提交内容摘要：
{submissions_summary}

请按照以下结构输出 JSON 格式的 Skill 内容：

{{
    "name": "技能名称（小写连字符，如 poetry-composition-with-techniques）",
    "description": "一句话说明这个技能解决什么问题，适用于什么场景",
    "usage": "具体使用步骤，如：1. 分析用户需求；2. 选择合适的方法；3. 执行并验证",
    "instructions": "详细的核心指令，包括通用原则、方法选择指南、执行要点等",
    "examples": "至少一个完整的输入输出示例，展示如何调用该技能",
    "code_template": "如有可复用代码模板则输出，否则留空"
}}

要求：
1. 提炼出**可复用的通用方法论**，而非对本次任务的简单描述。
2. 从多个提交中归纳共同的最佳实践。
3. 输出内容应能直接作为 Agent Skill 使用。

只输出 JSON，不要包含其他内容。
"""

class BountyHub:
    def __init__(self, wallet: TokenWallet):
        self.wallet = wallet
        self.relation_manager = NodeRelationManager()
        self.container_ports = {}  # conversation_id -> port
        self.orchestrator = None  # orchestrator 引用

    def set_container_ports(self, ports: dict):
        """设置容器端口映射，由 bff_service 调用"""
        self.container_ports = ports

    def set_orchestrator(self, orch):
        """设置容器编排器引用"""
        self.orchestrator = orch

    def get_container_url(self, conversation_id: str) -> str:
        """获取容器 URL"""
        port = self.container_ports.get(conversation_id)
        if not port:
            return None
        return f"http://localhost:{port}"

    async def create_bounty(self, issuer_id: str, title: str, description: str, reward_pool: int, deadline: datetime, docker_reward: int = 0) -> str:
        print(f"[BountyHub] 创建悬赏: issuer={issuer_id}, title={title}, reward={reward_pool}")
        await self.wallet.transfer(issuer_id, "system", reward_pool, "bounty_lock")
        bounty_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute("""
                INSERT INTO bounties (id, issuer_id, title, description, reward_pool, docker_reward, deadline, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)
            """, (bounty_id, issuer_id, title, description, reward_pool, docker_reward, deadline, datetime.now()))

        # 自动分发给邻居节点
        try:
            await self.notify_neighbors(issuer_id, bounty_id)
        except Exception as e:
            print(f"[BountyHub] 通知邻居失败: {e}")

        return bounty_id
    
    async def notify_neighbors(self, issuer_id: str, bounty_id: str):
        """通知邻居节点"""
        # 获取邻居节点
        neighbors = await self.relation_manager.get_neighbors(issuer_id)
        print(f"[BountyHub] notify_neighbors: issuer={issuer_id}, bounty={bounty_id}, 邻居数={len(neighbors)}")

        if not neighbors:
            print(f"[BountyHub] 警告: 发布者 {issuer_id} 没有邻居节点，无法通知！")
            return

        # 按边权排序
        neighbors.sort(key=lambda x: x['weight'], reverse=True)

        # 通知邻居节点
        for neighbor in neighbors:
            # 创建任务通知
            notification_id = str(uuid.uuid4())
            with get_db() as conn:
                conn.execute("""
                    INSERT INTO notifications (id, node_id, bounty_id, type, status, created_at)
                    VALUES (?, ?, ?, 'bounty', 'pending', ?)
                """, (notification_id, neighbor['node_id'], bounty_id, datetime.now()))
            print(f"[BountyHub] 创建通知: notification={notification_id}, node={neighbor['node_id']}")

    async def submit_solution(self, bounty_id: str, agent_id: str, content: str, skill_code: str = None, cost_tokens: int = 0) -> str:
        # 检查是否已有该节点对该 bounty 的提交（防止重复提交）
        with get_db() as conn:
            existing = conn.execute("""
                SELECT id FROM submissions WHERE bounty_id = ? AND agent_id = ?
            """, (bounty_id, agent_id)).fetchone()
            if existing:
                print(f"[BountyHub] 该节点已提交过，跳过: bounty_id={bounty_id}, agent_id={agent_id}")
                return existing["id"]

        if cost_tokens > 0:
            await self.wallet.transfer(agent_id, "system", cost_tokens, "bounty_participation", bounty_id)
        sub_id = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute("""
                INSERT INTO submissions (id, bounty_id, agent_id, content, skill_code, cost_tokens, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (sub_id, bounty_id, agent_id, content, skill_code, cost_tokens, datetime.now()))
        print(f"[BountyHub] 提交成功: bounty_id={bounty_id}, agent_id={agent_id}, sub_id={sub_id}")
        return sub_id

    async def evaluate_and_reward(self, bounty_id: str, winner_submission_ids: List[str], scores: List[float]):
        with get_db() as conn:
            row = conn.execute("SELECT reward_pool FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
            if not row:
                raise ValueError("Bounty not found")
            reward_pool = row["reward_pool"]
        ratios = [0.5, 0.3, 0.2]
        for i, sub_id in enumerate(winner_submission_ids):
            if i >= len(ratios):
                break
            amount = int(reward_pool * ratios[i])
            with get_db() as conn:
                agent_row = conn.execute("SELECT agent_id FROM submissions WHERE id = ?", (sub_id,)).fetchone()
                if not agent_row:
                    continue
                agent_id = agent_row["agent_id"]
            await self.wallet.transfer("system", agent_id, amount, "bounty_reward", bounty_id)
            with get_db() as conn:
                conn.execute("UPDATE submissions SET evaluation_score = ? WHERE id = ?", (scores[i], sub_id))
        with get_db() as conn:
            conn.execute("UPDATE bounties SET status = 'closed', winner_ids = ? WHERE id = ?",
                         (",".join(winner_submission_ids), bounty_id))

    async def list_open_bounties(self) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM bounties WHERE status = 'open' AND deadline > ?", (datetime.now(),)).fetchall()
            return [dict(row) for row in rows]

    async def get_bounty(self, bounty_id: str) -> Optional[dict]:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
            if row:
                return dict(row)
            return None

    async def get_submissions(self, bounty_id: str) -> List[dict]:
        with get_db() as conn:
            rows = conn.execute("SELECT * FROM submissions WHERE bounty_id = ?", (bounty_id,)).fetchall()
            return [dict(row) for row in rows]

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

        try:
            # 1. 验证发布者身份
            print(f"[BountyHub] [Step 1] 验证发布者身份...")
            with get_db() as conn:
                row = conn.execute("SELECT issuer_id FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
                if not row:
                    print(f"[BountyHub] [Step 1] 错误: 悬赏任务不存在")
                    raise ValueError("Bounty not found")
                if row["issuer_id"] != issuer_id:
                    print(f"[BountyHub] [Step 1] 错误: 只有发布者可以关闭任务")
                    raise ValueError("Only issuer can close bounty")
                print(f"[BountyHub] [Step 1] 验证通过")

            # 2. 获取所有提交
            print(f"[BountyHub] [Step 2] 获取所有提交...")
            submissions = await self.get_submissions(bounty_id)
            print(f"[BountyHub] [Step 2] 找到 {len(submissions)} 个提交")

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
                # 3. 自动评级（使用发布者的容器进行评分）
                print(f"[BountyHub] [Step 3] 开始自动评级...")

                # 3.1 准备评审数据（提取文件）
                print(f"[BountyHub] [Step 3.1] 准备评审数据...")
                review_data = await self._prepare_review_data(bounty_id, submissions)
                review_root = review_data.get("review_root", "")

                # 3.2 复制到发布者容器
                container_review_path = None
                if self.get_container_url(issuer_id):
                    print(f"[BountyHub] [Step 3.2] 复制评审数据到发布者容器...")
                    container_review_path = await self._copy_review_to_container(issuer_id, review_root)

                # 3.3 执行评审
                print(f"[BountyHub] [Step 3.3] 执行评审...")
                issuer_container_url = self.get_container_url(issuer_id)
                if container_review_path and issuer_container_url:
                    evaluation_results = await self._evaluate_with_files(
                        issuer_id, bounty_id, container_review_path, review_data["submissions"],
                        original_submissions=submissions
                    )
                elif issuer_container_url:
                    evaluation_results = await self._auto_evaluate_submissions(bounty_id, submissions, issuer_container_url)
                else:
                    evaluation_results = await self._auto_evaluate_submissions(bounty_id, submissions, None)

                result["evaluation_results"] = evaluation_results
                print(f"[BountyHub] [Step 3] 评级完成")

                # 3.4 清理评审数据
                await self._cleanup_review_data(review_root)

                # 4. 发放奖励
                print(f"[BountyHub] [Step 4] 开始发放奖励...")
                reward_results = await self._distribute_rewards(bounty_id, evaluation_results)
                result["reward_results"] = reward_results
                print(f"[BountyHub] [Step 4] 奖励发放完成")

                # 5. Skill 沉淀
                print(f"[BountyHub] [Step 5] 开始 Skill 沉淀...")
                curation_result = await self._auto_curate_best_skill(bounty_id, evaluation_results, issuer_id)
                result["curation_results"] = curation_result
                print(f"[BountyHub] [Step 5] Skill 沉淀完成")
                
                # 5b. 综合所有提交生成总结类Skill
                print(f"[BountyHub] [Step 5b] 开始生成综合报告Skill...")
                aggregated_result = await self._curate_aggregated_report(bounty_id, evaluation_results, issuer_id)
                if aggregated_result:
                    if result["curation_results"] is None:
                        result["curation_results"] = {"aggregated_report": aggregated_result}
                    elif isinstance(result["curation_results"], dict):
                        result["curation_results"]["aggregated_report"] = aggregated_result
                    print(f"[BountyHub] [Step 5b] 综合报告Skill生成完成")
                else:
                    print(f"[BountyHub] [Step 5b] 跳过综合报告Skill生成")

            # 6. 更新边权
            print(f"[BountyHub] [Step 6] 开始更新边权...")
            await self.update_edge_weights_after_bounty(issuer_id, bounty_id)
            print(f"[BountyHub] [Step 6] 边权更新完成")

            # 7. 更新任务状态
            print(f"[BountyHub] [Step 7] 更新任务状态为 completed...")
            with get_db() as conn:
                conn.execute("UPDATE bounties SET status = 'completed' WHERE id = ?", (bounty_id,))

            # 8. 生成结算报告
            print(f"[BountyHub] [Step 8] 生成结算报告...")
            report_path = await self._generate_settlement_report(bounty_id, result)
            if report_path:
                print(f"[BountyHub] [Step 8] 结算报告已生成: {report_path}")
            else:
                print(f"[BountyHub] [Step 8] 跳过结算报告生成")

            print(f"[BountyHub] ===== 悬赏任务关闭完成 =====")
            print(f"[BountyHub] 最终结果: {result}")

            return result
            
        except Exception as e:
            print(f"[BountyHub] ❌ 关闭任务过程中发生未捕获异常: {e}")
            import traceback
            traceback.print_exc()
            try:
                with get_db() as conn:
                    conn.execute("UPDATE bounties SET status = 'error' WHERE id = ?", (bounty_id,))
            except:
                pass
            return {
                "status": "error",
                "error": str(e),
                "bounty_id": bounty_id,
                "submissions_count": len(submissions) if 'submissions' in dir() else 0,
                "evaluation_results": result.get("evaluation_results", []) if 'result' in dir() else [],
                "reward_results": [],
                "curation_results": None
            }

    async def _prepare_review_data(self, bounty_id: str, submissions: List[dict]) -> dict:
        """
        准备评审数据，从各提交者容器提取文件到宿主机临时目录。
        返回评审目录信息和提交列表。
        """
        print(f"[BountyHub] [_prepare_review] 开始准备评审数据...")
        print(f"[BountyHub] [_prepare_review] 提交者数量: {len(submissions)}")

        review_root = Path(tempfile.mkdtemp(prefix=f"bounty_review_{bounty_id[:8]}_"))
        print(f"[BountyHub] [_prepare_review] 评审目录: {review_root}")

        submission_files = []
        for sub in submissions:
            agent_id = sub.get("agent_id", "")
            if not agent_id:
                continue

            print(f"[BountyHub] [_prepare_review] 处理提交者: {agent_id}")

            agent_dir = review_root / agent_id
            agent_dir.mkdir(exist_ok=True)

            # 写入数据库中的 content 作为 fallback
            content = sub.get("content", "")
            if content:
                print(f"[BountyHub] [_prepare_review]   - 数据库 content 长度: {len(content)}")
                with open(agent_dir / "submission.txt", "w") as f:
                    f.write(content)
            else:
                print(f"[BountyHub] [_prepare_review]   - 数据库 content 为空")

            # 尝试从容器提取文件
            if self.orchestrator:
                try:
                    print(f"[BountyHub] [_prepare_review]   - 调用 extract_workspace_files...")
                    extracted = await self.orchestrator.extract_workspace_files(
                        agent_id,
                        str(agent_dir),
                        file_patterns=["*.md", "*.txt", "*.py", "solution*"]
                    )
                    print(f"[BountyHub] [_prepare_review]   - 提取结果: {extracted}")
                    if extracted:
                        print(f"[BountyHub] [_prepare_review]   - 从 {agent_id} 提取了 {len(extracted)} 个文件")
                    else:
                        print(f"[BountyHub] [_prepare_review]   - 未提取到任何文件")
                except Exception as e:
                    print(f"[BountyHub] [_prepare_review]   - 提取 {agent_id} 文件失败: {e}")

            # 列出 agent_dir 下的所有文件
            extracted_files = list(agent_dir.glob("*"))
            print(f"[BountyHub] [_prepare_review]   - agent_dir 下的文件: {[f.name for f in extracted_files]}")

            submission_files.append({
                "submission_id": sub.get("id"),
                "agent_id": agent_id,
                "content": content
            })

        # 写入元信息
        bounty = await self.get_bounty(bounty_id)
        metadata = {
            "bounty_id": bounty_id,
            "title": bounty.get("title") if bounty else "",
            "description": bounty.get("description") if bounty else "",
            "deadline": str(bounty.get("deadline")) if bounty else "",
            "submissions": [{"agent_id": s["agent_id"], "submission_id": s.get("id")} for s in submissions]
        }
        with open(review_root / "metadata.json", "w") as f:
            json.dump(metadata, f, ensure_ascii=False)

        print(f"[BountyHub] [_prepare_review] 评审数据准备完成，共 {len(submission_files)} 个提交")

        return {
            "review_root": str(review_root),
            "submissions": submission_files,
            "metadata": metadata
        }

    async def _cleanup_review_data(self, review_root: str):
        """清理评审数据目录"""
        if review_root and os.path.exists(review_root):
            try:
                shutil.rmtree(review_root)
                print(f"[BountyHub] [_cleanup] 已清理评审目录: {review_root}")
            except Exception as e:
                print(f"[BountyHub] [_cleanup] 清理失败: {e}")

    async def _copy_review_to_container(self, issuer_id: str, review_root: str) -> str:
        """
        将评审目录复制到发布者容器内，返回容器内路径。
        """
        if not self.orchestrator:
            return None

        try:
            container_name = f"nanobot_conv_{issuer_id}"
            container = self.orchestrator.docker_client.containers.get(container_name)

            container_review_path = f"/tmp/review_{os.path.basename(review_root)}"

            import tarfile
            import io

            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(review_root, arcname=os.path.basename(container_review_path))
            tar_stream.seek(0)

            container.put_archive("/tmp", tar_stream)
            print(f"[BountyHub] [_copy_review] 已复制到容器 {issuer_id}:{container_review_path}")

            return container_review_path

        except Exception as e:
            print(f"[BountyHub] [_copy_review] 复制到容器失败: {e}")
            return None

    async def _evaluate_with_files(
        self,
        issuer_id: str,
        bounty_id: str,
        container_review_path: str,
        review_submissions: list,
        original_submissions: list = None
    ) -> list:
        """
        使用发布者容器进行文件级评审。
        若失败则降级到 JSON 评审，此时使用原始提交数据。
        """
        print(f"[BountyHub] [_evaluate_files] 开始文件级评审...")

        container_url = self.get_container_url(issuer_id)
        if not container_url:
            print(f"[BountyHub] [_evaluate_files] 无法获取容器 URL，降级到 JSON 评审")
            return await self._auto_evaluate_submissions(bounty_id, original_submissions or review_submissions, None)

        bounty = await self.get_bounty(bounty_id)
        bounty_title = bounty.get("title", "") if bounty else ""
        bounty_desc = bounty.get("description", "") if bounty else ""

        payload = {
            "bounty_id": bounty_id,
            "bounty_title": bounty_title,
            "bounty_description": bounty_desc,
            "review_base_path": container_review_path,
            "submissions": review_submissions
        }

        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=120)) as session:
                async with session.post(
                    f"{container_url}/evaluate_batch",
                    json=payload
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        results = data.get("results", [])
                        print(f"[BountyHub] [_evaluate_files] 批量评审成功: {len(results)} 个结果")
                        return results
                    else:
                        error_text = await resp.text()
                        print(f"[BountyHub] [_evaluate_files] 批量评审失败: {resp.status}, {error_text}")
        except Exception as e:
            print(f"[BountyHub] [_evaluate_files] 批量评审异常: {e}")

        # 降级到 JSON 评审，使用原始提交数据
        print(f"[BountyHub] [_evaluate_files] 降级到 JSON 评审")
        return await self._auto_evaluate_submissions(bounty_id, original_submissions or review_submissions, container_url)

    async def _auto_evaluate_submissions(self, bounty_id: str, submissions: List[dict], evaluator_container_url: str = None) -> List[dict]:
        """
        自动评级提交（使用 LLM 评分）
        evaluator_container_url: 评分用的容器URL（发布者的容器）
        """
        print(f"[BountyHub] [_auto_evaluate] 开始评级 {len(submissions)} 个提交...")

        # 获取 bounty 详情用于评分
        bounty = await self.get_bounty(bounty_id)
        if not bounty:
            print(f"[BountyHub] [_auto_evaluate] 警告: 无法获取 bounty {bounty_id} 详情，使用空对象")
            bounty = {}
        else:
            print(f"[BountyHub] [_auto_evaluate] bounty: {bounty.get('title', 'N/A')}")

        evaluation_results = []
        evaluator = SubmissionEvaluator()

        for i, sub in enumerate(submissions):
            sub_id = sub.get("id")
            if not sub_id:
                print(f"[BountyHub] [_auto_evaluate] 跳过无效提交（缺少id）: {sub}")
                continue
            agent_id = sub.get("agent_id", "")

            print(f"[BountyHub] [_auto_evaluate] 提交 {i+1}: id={sub_id}, agent={agent_id}")

            # 使用发布者的容器进行评分
            container_url = evaluator_container_url
            if container_url:
                print(f"[BountyHub] [_auto_evaluate]   - 使用发布者容器评分: {container_url}")
            else:
                print(f"[BountyHub] [_auto_evaluate]   - 无容器URL，使用规则评分")

            # 使用容器或规则评分（同时获取 Skill 总结）
            score, reason, skill_summary = await evaluator.evaluate_with_skill_summary(bounty, sub, container_url)

            # 更新数据库（只更新评分和理由）
            with get_db() as conn:
                conn.execute(
                    "UPDATE submissions SET score = ?, score_reason = ? WHERE id = ?",
                    (score, reason, sub_id)
                )

            result = {
                "submission_id": sub_id,
                "agent_id": sub["agent_id"],
                "score": score,
                "reason": reason,
                "skill_summary": skill_summary if skill_summary else {}
            }
            evaluation_results.append(result)

            # 记录 Skill 总结状态
            if skill_summary:
                skill_name = skill_summary.get("name", "unknown")
                print(f"[BountyHub] [_auto_evaluate]   - 评分: {score}, 已生成 Skill: {skill_name}")
            else:
                print(f"[BountyHub] [_auto_evaluate]   - 评分: {score}, 理由: {reason}")

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
                print(f"[BountyHub] [_distribute] 错误: 悬赏任务不存在")
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
        注意：skill_code 是可选的，即使没有 skill_code 也应该能沉淀 Skill
        """
        print(f"[BountyHub] [_curate] 开始 Skill 沉淀...")

        if not evaluation_results:
            print(f"[BountyHub] [_curate] 没有评级结果，跳过 Skill 沉淀")
            return None

        best = evaluation_results[0]
        print(f"[BountyHub] [_curate] 最佳提交数据: {best}")

        with get_db() as conn:
            sub_row = conn.execute("SELECT content, skill_code FROM submissions WHERE id = ?",
                                  (best["submission_id"],)).fetchone()

        if not sub_row:
            print(f"[BountyHub] [_curate] 最佳提交不存在，跳过 Skill 沉淀")
            return None

        if not sub_row["content"] and not sub_row["skill_code"]:
            print(f"[BountyHub] [_curate] 最佳提交没有内容，跳过 Skill 沉淀")
            return None

        print(f"[BountyHub] [_curate] 最佳提交: {best['submission_id']}")
        if sub_row["skill_code"]:
            print(f"[BountyHub] [_curate] Skill Code 长度: {len(sub_row['skill_code'])}")

        try:
            from bff.public_space import PublicSpace as PS
            public_space = PS()

            doc_id = await self.curate_skill_to_public(
                bounty_id=bounty_id,
                submission_id=best["submission_id"],
                issuer_id=issuer_id,
                tags=["bounty", "auto-curated", f"score:{best['score']}"],
                skill_summary=best.get("skill_summary")
            )

            from shared.config import SKILL_EXPORT_DIR
            try:
                export_path = await public_space.export_skill_as_markdown(doc_id, SKILL_EXPORT_DIR)
                print(f"[BountyHub] [_curate] Skill 导出成功: {export_path}")
            except Exception as e:
                print(f"[BountyHub] [_curate] Skill 导出失败: {e}")
                export_path = None

            print(f"[BountyHub] [_curate] Skill 沉淀成功! doc_id={doc_id}")
            return {
                "status": "success",
                "doc_id": doc_id,
                "submission_id": best["submission_id"],
                "score": best["score"],
                "export_path": export_path
            }
        except Exception as e:
            print(f"[BountyHub] [_curate] Skill 沉淀失败: {e}")
            return {
                "status": "failed",
                "error": str(e)
            }

    async def update_edge_weights_after_bounty(self, issuer_id: str, bounty_id: str):
        """任务结束后，增加发起者与参与者之间的边权"""
        try:
            # 获取所有参与该任务的节点
            with get_db() as conn:
                rows = conn.execute("""
                    SELECT DISTINCT agent_id FROM submissions WHERE bounty_id = ?
                """, (bounty_id,)).fetchall()

            participants = [row["agent_id"] for row in rows]
            print(f"[BountyHub] 任务参与者: {participants}")

            # 增加与每个参与者的边权
            for participant_id in participants:
                if participant_id == issuer_id:
                    continue  # 跳过自己

                # 查找现有边权
                existing = await self.relation_manager.get_relation(issuer_id, participant_id)
                if existing:
                    # 增加边权
                    new_weight = existing["weight"] + 1
                    await self.relation_manager.update_weight(issuer_id, participant_id, new_weight)
                    print(f"[BountyHub] 更新边权: {issuer_id} <-> {participant_id}: {existing['weight']} -> {new_weight}")
                else:
                    # 创建新边权，初始值为 1
                    await self.relation_manager.add_relation(issuer_id, participant_id, 1)
                    print(f"[BountyHub] 创建边权: {issuer_id} <-> {participant_id}: 1")

            print(f"[BountyHub] 边权更新完成")
        except Exception as e:
            print(f"[BountyHub] 更新边权失败: {e}")

    async def curate_skill_to_public(self, bounty_id: str, submission_id: str, issuer_id: str, tags: list = None, skill_summary: dict = None) -> str:
        """将优秀的 skill 整理到公共知识库，优先使用已有的 Skill 总结，否则使用 LLM 总结"""
        # 验证发布者身份
        with get_db() as conn:
            bounty_row = conn.execute("SELECT issuer_id, description FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
            if not bounty_row or bounty_row["issuer_id"] != issuer_id:
                raise ValueError("Only issuer can curate skill")
            
            # 获取 submission 信息
            sub_row = conn.execute("SELECT content, skill_code FROM submissions WHERE id = ?", (submission_id,)).fetchone()
            if not sub_row:
                raise ValueError("Submission not found")
        
        bounty_description = bounty_row["description"] or ""
        submission_content = sub_row["content"] or ""
        original_skill_code = sub_row["skill_code"] or ""
        
        print(f"[BountyHub] 开始处理 Skill: bounty_id={bounty_id}, 内容长度={len(submission_content)}")
        
        # 优先使用传入的 Skill 总结
        if skill_summary and isinstance(skill_summary, dict) and skill_summary.get("name"):
            print(f"[BountyHub] 使用已有的 Skill 总结: {skill_summary.get('name')}")
            skill_data = skill_summary
        else:
            print(f"[BountyHub] 没有 Skill 总结，使用 LLM 重新总结")
            # 使用 LLM 总结提交内容为标准化 Skill
            from bff.public_space import PublicSpace
            public_space = PublicSpace()
            
            skill_data = await public_space.summarize_submission_to_skill(
                submission_content=submission_content,
                bounty_description=bounty_description
            )
        
        # 提取 Skill 信息
        skill_name = skill_data.get("name", f"skill-from-bounty-{bounty_id}")
        skill_description = skill_data.get("description", "未提供描述")
        skill_usage = skill_data.get("usage", skill_data.get("instructions", "请参考下方说明"))
        skill_instructions = skill_data.get("instructions", skill_description)
        skill_examples = skill_data.get("examples", "")
        skill_code_template = skill_data.get("code_template", original_skill_code)
        
        # 组合 content 字段：包含完整的 Skill 信息
        full_content = f"""# {skill_name}

## 技能描述
{skill_description}

## 核心指令
{skill_instructions}

## 使用示例
{skill_examples}

## 原始提交内容（参考）
{submission_content[:1000] if submission_content else "无"}
"""
        
        # 存储到公共知识库
        from bff.public_space import PublicSpace
        public_space = PublicSpace()
        doc_id = await public_space.add_knowledge(
            knowledge_type="skill",
            title=skill_name,
            content=full_content,
            skill_code=skill_code_template,
            usage=skill_usage,
            tags=tags or [],
            author_id=issuer_id
        )
        
        print(f"[BountyHub] ✅ Skill 沉淀成功: {skill_name}, doc_id={doc_id}")
        return doc_id

    async def _curate_aggregated_report(self, bounty_id: str, evaluation_results: list, issuer_id: str) -> dict:
        """综合所有提交内容，生成一份总结性质的 Skill 报告"""
        print(f"[BountyHub] [_aggregated_report] 开始生成综合报告 Skill...")
        
        high_quality_subs = [r for r in evaluation_results if r.get("score", 0) >= 80]
        if len(high_quality_subs) < 2:
            print(f"[BountyHub] [_aggregated_report] 高质量提交不足 ({len(high_quality_subs)}个)，跳过综合报告生成")
            return None
        
        print(f"[BountyHub] [_aggregated_report] 找到 {len(high_quality_subs)} 个高质量提交（分数 ≥ 80）")
        print(f"[BountyHub] [_aggregated_report] 高质量提交数据: {high_quality_subs}")
        
        # 收集这些提交的内容
        submissions_content = []
        for sub in high_quality_subs:
            with get_db() as conn:
                row = conn.execute("SELECT content FROM submissions WHERE id = ?", (sub["submission_id"],)).fetchone()
                if row and row["content"]:
                    submissions_content.append(row["content"])
        
        if not submissions_content:
            print(f"[BountyHub] [_aggregated_report] 没有找到可用的提交内容")
            return None
        
        print(f"[BountyHub] [_aggregated_report] 收集到 {len(submissions_content)} 个提交内容，总长度: {sum(len(c) for c in submissions_content)}")
        
        try:
            # 获取悬赏任务描述
            with get_db() as conn:
                bounty_row = conn.execute("SELECT description FROM bounties WHERE id = ?", (bounty_id,)).fetchone()
                bounty_description = bounty_row["description"] if bounty_row else ""
            
            # 合并所有提交内容用于生成综合报告
            combined_content = "=== 所有高质量提交内容摘要 ===\n\n"
            for i, content in enumerate(submissions_content):
                combined_content += f"提交 #{i+1} (分数: {high_quality_subs[i]['score']}分):\n{content}\n\n" + "="*50 + "\n\n"
            
            print(f"[BountyHub] [_aggregated_report] 开始生成综合 Skill 总结...")
            
            # 使用现有的 LLM 总结功能生成综合报告
            # 这里我们创建一个特殊的综合总结 prompt
            from bff.public_space import PublicSpace
            public_space = PublicSpace()
            
            # 由于现有的 summarize_submission_to_skill 是针对单个提交的，
            # 我们需要调整使用方式。这里我们创建一个综合内容的伪提交
            # 注意：内容限制已增加到 20000，避免双重截断丢失信息
            aggregated_submission = f"""这是基于多个高质量提交（分数 ≥ 80）的综合分析报告：

悬赏任务描述: {bounty_description}

提交数量: {len(submissions_content)}
平均分数: {sum(s['score'] for s in high_quality_subs) / len(high_quality_subs):.1f}

请综合分析以下所有提交，提取共同特点、最佳实践和通用模式，总结成一个标准化的综合性 Agent Skill。

所有提交内容:
{combined_content[:20000]}  # 限制长度以避免 token 超限（增大到20000避免双重截断）

请生成一个综合性的 Skill 报告，包含以下部分：
1. 综合技能名称和描述
2. 从所有提交中提取的最佳实践
3. 共同模式和通用解决方案
4. 改进建议和未来方向
5. 对各提交的简要分析

格式请参考标准的 Skill 总结格式，但作为综合报告。"""
            
            # 调用 LLM 生成综合 Skill 总结（使用专用 Prompt）
            prompt = AGGREGATED_REPORT_PROMPT.format(
                bounty_description=bounty_description[:500],
                submission_count=len(submissions_content),
                avg_score=sum(s['score'] for s in high_quality_subs) / len(high_quality_subs),
                submissions_summary=combined_content[:8000]
            )

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300)) as session:
                async with session.post(
                    "https://api.deepseek.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {DEEPSEEK_API_KEY}"},
                    json={
                        "model": "deepseek-chat",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.3,
                        "max_tokens": 1500
                    }
                ) as resp:
                    response_data = await resp.json()
                    content = response_data["choices"][0]["message"]["content"]
                    skill_data = json.loads(extract_json(content))
            
            # 调整技能名称和描述以表明这是综合报告
            skill_name = skill_data.get("name", f"aggregated-report-{bounty_id[:8]}")
            if not skill_name.startswith("aggregated-"):
                skill_name = f"aggregated-{skill_name}"
            
            skill_description = skill_data.get("description", f"基于 {len(submissions_content)} 个高质量提交的综合报告")
            if "综合" not in skill_description and "聚合" not in skill_description:
                skill_description = f"综合报告: {skill_description}"
            
            skill_usage = skill_data.get("usage", "提供对该悬赏任务的全局视角和综合解决方案")
            skill_instructions = skill_data.get("instructions", skill_description)
            
            # 组合 content 字段：包含完整的综合报告信息
            full_content = f"""# {skill_name}

## 综合报告概述
{skill_description}

## 综合最佳实践
{skill_instructions}

## 报告详情
本次综合报告基于 {len(submissions_content)} 个高质量提交（分数 ≥ 70）。
平均分数: {sum(s['score'] for s in high_quality_subs) / len(high_quality_subs):.1f}
提交ID列表: {', '.join([s['submission_id'][:8] for s in high_quality_subs])}

## 详细分析
{skill_data.get('examples', '无详细分析')}

## 原始提交摘要（部分）
{combined_content[:2000] if combined_content else "无"}
"""
            
            # 存储到公共知识库
            doc_id = await public_space.add_knowledge(
                knowledge_type="skill",
                title=skill_name,
                content=full_content,
                skill_code="",  # 综合报告没有具体的代码模板
                usage=skill_usage,
                tags=["bounty", "aggregated-report", f"submissions:{len(submissions_content)}", f"avg-score:{sum(s['score'] for s in high_quality_subs) / len(high_quality_subs):.1f}"],
                author_id=issuer_id
            )
            
            # 导出综合报告
            from shared.config import SKILL_EXPORT_DIR
            try:
                export_path = await public_space.export_skill_as_markdown(doc_id, SKILL_EXPORT_DIR)
                print(f"[BountyHub] [_aggregated_report] 综合报告导出成功: {export_path}")
            except Exception as e:
                print(f"[BountyHub] [_aggregated_report] 综合报告导出失败: {e}")
                export_path = None
            
            print(f"[BountyHub] [_aggregated_report] ✅ 综合报告 Skill 生成成功! doc_id={doc_id}")
            return {
                "status": "success",
                "doc_id": doc_id,
                "type": "aggregated_report",
                "submissions_count": len(submissions_content),
                "average_score": sum(s['score'] for s in high_quality_subs) / len(high_quality_subs),
                "export_path": export_path
            }
        except Exception as e:
            print(f"[BountyHub] [_aggregated_report] ❌ 综合报告生成失败: {e}")
            import traceback
            traceback.print_exc()
            return {
                "status": "failed",
                "error": str(e),
                "type": "aggregated_report"
            }

    async def _generate_settlement_report(self, bounty_id: str, close_result: dict) -> Optional[str]:
        """
        生成悬赏结算报告到 xuanshang_report 文件夹
        返回报告文件路径，失败返回 None
        """
        try:
            bounty = await self.get_bounty(bounty_id)
            if not bounty:
                print(f"[BountyHub] [_settlement_report] 悬赏不存在，跳过报告生成")
                return None

            os.makedirs(XUANSHANG_REPORT_DIR, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_filename = f"bounty_settlement_{bounty_id[:8]}_{timestamp}.md"
            report_path = os.path.join(XUANSHANG_REPORT_DIR, report_filename)

            evaluation_results = close_result.get("evaluation_results", [])
            reward_results = close_result.get("reward_results", [])

            ranked_results = sorted(evaluation_results, key=lambda x: x.get("score", 0), reverse=True)

            report_lines = [
                f"# 悬赏结算报告",
                f"",
                f"**悬赏ID**: {bounty_id}",
                f"**悬赏标题**: {bounty.get('title', 'N/A')}",
                f"**悬赏描述**: {bounty.get('description', 'N/A')}",
                f"**发布时间**: {bounty.get('created_at', 'N/A')}",
                f"**结算时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"**状态**: {close_result.get('status', 'unknown')}",
                f"",
                f"---",
                f"",
                f"## 提交情况",
                f"",
                f"- **提交总数**: {close_result.get('submissions_count', 0)}",
                f"- **有效评审数**: {len(evaluation_results)}",
                f"",
                f"---",
                f"",
                f"## 排名结果",
                f"",
            ]

            for i, r in enumerate(ranked_results):
                rank = i + 1
                medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"#{rank}"
                report_lines.append(f"### {medal} 第{rank}名")
                report_lines.append(f"- **提交ID**: {r.get('submission_id', 'N/A')[:16]}...")
                report_lines.append(f"- **AgentID**: {r.get('agent_id', 'N/A')[:16]}...")
                report_lines.append(f"- **评分**: {r.get('score', 0):.1f}/100")
                report_lines.append(f"- **评分理由**: {r.get('reason', 'N/A')}")

                skill_summary = r.get("skill_summary")
                if skill_summary:
                    report_lines.append(f"- **Skill名称**: {skill_summary.get('name', 'N/A')}")
                report_lines.append("")

            if reward_results:
                report_lines.extend([
                    f"---",
                    f"",
                    f"## 奖励发放",
                    f"",
                ])
                for rw in reward_results:
                    agent = rw.get("agent_id", "N/A")[:16]
                    amount = rw.get("amount", 0)
                    status = rw.get("status", "unknown")
                    report_lines.append(f"- **{agent}...**: {amount} tokens - {status}")

            curation = close_result.get("curation_results")
            if curation and curation.get("status") == "success":
                report_lines.extend([
                    f"",
                    f"---",
                    f"",
                    f"## Skill沉淀",
                    f"",
                    f"- **最佳Skill**: {curation.get('skill_name', 'N/A')}",
                    f"- **沉淀时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                ])

            report_lines.extend([
                f"",
                f"---",
                f"",
                f"*本报告由 BountyHub 自动生成*",
            ])

            with open(report_path, "w", encoding="utf-8") as f:
                f.write("\n".join(report_lines))

            print(f"[BountyHub] [_settlement_report] 结算报告已保存: {report_path}")
            return report_path

        except Exception as e:
            print(f"[BountyHub] [_settlement_report] 生成结算报告失败: {e}")
            import traceback
            traceback.print_exc()
            return None