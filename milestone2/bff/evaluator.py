import os
import sys
import json
import re
import asyncio
import aiohttp
from typing import Tuple, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.config import DEEPSEEK_API_KEY

class SubmissionEvaluator:
    # 常量定义（宁缺毋滥策略）
    HIGH_SCORE_THRESHOLD = 80.0
    SKILL_SUMMARY_THRESHOLD = 80.0  # 分数高于80分时才进行Skill总结
    SKILL_SUMMARY_TIMEOUT = 300     # 5分钟，足够完成复杂评审
    EVALUATE_TIMEOUT = 300          # 5分钟，足够完成复杂评审
    LLM_TIMEOUT = 120               # 单个 LLM 调用也适当放宽
    LLM_MAX_TOKENS = 500
    LLM_TEMPERATURE = 0.3
    
    def __init__(self):
        self.deepseek_api_key = DEEPSEEK_API_KEY
        self.deepseek_api_url = "https://api.deepseek.com/v1/chat/completions"

    async def evaluate(self, bounty: dict, submission: dict, container_url: str = None) -> Tuple[float, str]:
        """
        对单个 submission 进行评分
        返回: (score, reason)
        score: 0-100 的评分
        reason: 评分理由
        container_url: 可选，容器URL，如果提供则使用容器进行评分
        """
        bounty_desc = bounty.get("description", "")
        submission_content = submission.get("content", "")

        print(f"[Evaluator] 开始评分: bounty_id={bounty.get('id')}, submission_id={submission.get('id')}")
        print(f"[Evaluator] 悬赏描述: {bounty_desc[:100]}...")
        print(f"[Evaluator] 提交内容: {submission_content[:100]}...")

        if not submission_content or len(submission_content.strip()) == 0:
            print(f"[Evaluator] 提交内容为空，返回最低分")
            return 0.0, "提交内容为空"

        # 优先使用容器进行评分
        if container_url:
            try:
                return await self._call_container_evaluate(container_url, bounty_desc, submission_content)
            except Exception as e:
                print(f"[Evaluator] 容器评分失败: {e}，回退到规则评分")

        # 回退到规则评分
        return self._rule_based_score(submission_content)

    async def _call_container_evaluate(self, container_url: str, bounty_desc: str, submission_content: str) -> Tuple[float, str]:
        """调用容器内的 /evaluate 端点进行评分"""
        url = f"{container_url}/evaluate"
        payload = {
            "bounty_description": bounty_desc,
            "submission_content": submission_content
        }

        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.EVALUATE_TIMEOUT)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"容器评分返回错误: {resp.status}, {error_text}")

                data = await resp.json()
                score = float(data.get("score", 50))
                reason = str(data.get("reason", ""))

                print(f"[Evaluator] 容器评分成功: score={score}, reason={reason}")
                return score, reason

    async def _call_llm(self, prompt: str) -> Tuple[float, str]:
        """调用 LLM API 进行评分"""
        if not self.deepseek_api_key:
            print(f"[Evaluator] 未配置 DEEPSEEK_API_KEY，使用规则评分")
            return self._rule_based_score(prompt)

        headers = {
            "Authorization": f"Bearer {self.deepseek_api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": self.LLM_TEMPERATURE,
            "max_tokens": self.LLM_MAX_TOKENS
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.LLM_TIMEOUT)) as session:
            async with session.post(self.deepseek_api_url, headers=headers, json=payload) as resp:
                if resp.status != 200:
                    print(f"[Evaluator] LLM API 返回错误: {resp.status}")
                    return self._rule_based_score(prompt)

                data = await resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                return self._parse_llm_response(content)

    def _parse_llm_response(self, content: str) -> Tuple[float, str]:
        """解析 LLM 返回的 JSON 内容"""
        try:
            json_str = content.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("```")[1]
                if json_str.startswith("json"):
                    json_str = json_str[4:]
            json_str = json_str.strip()

            result = json.loads(json_str)
            score = float(result.get("score", 50))
            reason = str(result.get("reason", ""))

            score = max(0, min(100, score))

            return score, reason
        except Exception as e:
            print(f"[Evaluator] 解析 LLM 返回失败: {e}, content={content[:200]}")
            return 50.0, "解析评分结果失败"

    def _rule_based_score(self, content: str) -> Tuple[float, str]:
        """基于内容的长度和结构进行简单评分（备用方案）"""
        content = content.strip()
        length = len(content)

        # 简单的启发式规则
        if length < 50:
            return 30.0, "内容过短，缺乏实质信息"
        elif length < 200:
            return 50.0, "内容较短，但可能包含基本信息"
        elif length < 500:
            return 70.0, "内容长度适中"
        elif length < 1000:
            return 80.0, "内容较为丰富"
        else:
            return 85.0, "内容非常详细"

    async def _call_container_summarize_skill(self, container_url: str, bounty_desc: str, submission_content: str) -> dict:
        """调用容器内的 /summarize_skill 端点进行 Skill 总结"""
        url = f"{container_url}/summarize_skill"
        payload = {
            "bounty_description": bounty_desc,
            "submission_content": submission_content
        }
        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.SKILL_SUMMARY_TIMEOUT)) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"容器 Skill 总结返回错误: {resp.status}, {error_text}")

                raw_text = await resp.text()
                print(f"[Evaluator] 容器返回原始文本 (前200字符): {raw_text[:200]}")

                # 1. 预处理：去除 BOM 头和首尾空白
                cleaned_text = raw_text.strip().lstrip('\ufeff')

                # 2. 尝试提取 JSON (兼容代码块包裹)
                json_str = cleaned_text
                if cleaned_text.startswith('```'):
                    # 移除 markdown 代码块标记
                    json_str = re.sub(r'^```(?:json)?\s*', '', cleaned_text)
                    json_str = re.sub(r'\s*```$', '', json_str)

                # 3. 安全解析 JSON
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError as e:
                    print(f"[Evaluator] JSON 解析失败: {e}")
                    # 降级处理：尝试使用正则提取 name 字段
                    name_match = re.search(r'"name"\s*:\s*"([^"]+)"', cleaned_text)
                    fallback_name = name_match.group(1) if name_match else "skill-fallback"
                    print(f"[Evaluator] 降级提取技能名: {fallback_name}")
                    return {
                        "name": fallback_name,
                        "description": "解析响应失败，已使用降级策略",
                        "usage": "",
                        "instructions": cleaned_text[:500]
                    }

                # 4. 兼容两种响应格式
                # 格式一：{"skill_summary": {...}}
                # 格式二：直接返回 skill 对象 {...}
                if "skill_summary" in data:
                    skill_data = data["skill_summary"]
                else:
                    skill_data = data

                # 确保必需字段存在
                skill_summary = {
                    "name": skill_data.get("name", "unknown"),
                    "description": skill_data.get("description", ""),
                    "usage": skill_data.get("usage", ""),
                    "instructions": skill_data.get("instructions", ""),
                    "examples": skill_data.get("examples", ""),
                    "code_template": skill_data.get("code_template", "")
                }

                print(f"[Evaluator] 解析成功，技能名称: {skill_summary['name']}")
                return skill_summary

    async def evaluate_with_skill_summary(self, bounty: dict, submission: dict, container_url: str = None) -> tuple:
        """
        对 submission 进行评分并生成 Skill 总结
        返回: (score, reason, skill_summary)
        score: 0-100 的评分
        reason: 评分理由
        skill_summary: Skill 总结信息（可能为空字典）
        """
        bounty_desc = bounty.get("description", "")
        submission_content = submission.get("content", "")

        print(f"[Evaluator] 开始评分和Skill总结: bounty_id={bounty.get('id')}, submission_id={submission.get('id')}")

        if not submission_content or len(submission_content.strip()) == 0:
            print(f"[Evaluator] 提交内容为空，返回最低分")
            return 0.0, "提交内容为空", {}

        # 优先使用容器进行评分
        if container_url:
            try:
                # 先进行评分
                score, reason = await self._call_container_evaluate(container_url, bounty_desc, submission_content)
                
                # 宁缺毋滥策略：80分以上总结，否则据实汇报
                skill_summary = {}
                if score > self.SKILL_SUMMARY_THRESHOLD:
                    print(f"[Evaluator] 提交分数{score}分 > {self.SKILL_SUMMARY_THRESHOLD}分，开始Skill总结")
                    try:
                        skill_summary = await self._call_container_summarize_skill(container_url, bounty_desc, submission_content)
                    except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as e:
                        print(f"[Evaluator] Skill 总结失败（网络/解析错误）: {e}，继续返回评分结果")
                        skill_summary = {}
                    except Exception as e:
                        # 其他未预期的异常，记录堆栈但继续流程
                        print(f"[Evaluator] Skill 总结发生未预期错误: {e}")
                        import traceback
                        traceback.print_exc()
                        skill_summary = {}
                else:
                    print(f"[Evaluator] 提交分数{score}分 ≤ {self.SKILL_SUMMARY_THRESHOLD}分，不进行Skill总结（宁缺毋滥）")
                
                return score, reason, skill_summary
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                print(f"[Evaluator] 容器评分失败（网络/超时错误）: {e}，回退到规则评分")
                # 回退到规则评分
                score, reason = self._rule_based_score(submission_content)
                return score, reason, {}
            except Exception as e:
                # 其他未预期的异常（如代码逻辑错误），重新抛出以便调试
                print(f"[Evaluator] 容器评分发生未预期错误: {e}")
                import traceback
                traceback.print_exc()
                raise
        
        # 回退到规则评分（无容器）
        score, reason = self._rule_based_score(submission_content)
        return score, reason, {}

    async def evaluate_batch(self, bounty: dict, submissions: list, container_url: str = None) -> list:
        """
        批量评分，支持容器评分和 Skill 总结
        container_url: 可选，容器URL，如果提供则使用容器进行评分和Skill总结
        """
        results = []
        for sub in submissions:
            score, reason, skill_summary = await self.evaluate_with_skill_summary(bounty, sub, container_url)
            
            result = {
                "submission_id": sub.get("id"),
                "agent_id": sub.get("agent_id"),
                "score": score,
                "reason": reason
            }
            
            # 如果生成了 Skill 总结，添加到结果中
            if skill_summary:
                result["skill_summary"] = skill_summary
            
            results.append(result)
            
            print(f"[Evaluator] 批量评分完成: submission_id={sub.get('id')}, score={score}, skill_summary={bool(skill_summary)}")
        
        print(f"[Evaluator] 批量评分全部完成: {len(results)} 个提交")
        return results
