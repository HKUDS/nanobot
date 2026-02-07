"""对话总结器 - 提取和总结对话信息。"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger


@dataclass
class DailySummary:
    """每日概要数据结构"""

    date: str  # "2026-02-07"
    topics: list[str]  # 主要话题
    user_preferences: dict[str, str]  # 用户偏好
    decisions: list[str]  # 重要决定
    tasks: list[str]  # 待办事项
    technical_issues: list[dict]  # 技术问题 [{question, solution}]
    key_insights: list[str]  # 关键洞察


@dataclass
class TechnicalIssue:
    """技术问题数据结构"""

    question: str
    solution: str
    timestamp: str


class ConversationSummarizer:
    """对话总结器 - 提取和总结对话信息。"""

    def __init__(self, workspace: Path, provider: Any, model: str | None = None):
        self.workspace = workspace
        self.provider = provider
        self.model = self._get_model(model)
        self.memory_dir = workspace / "memory"
        self.sessions_dir = Path.home() / ".nanobot" / "sessions"

    def _get_model(self, model: str | None) -> str:
        """获取总结使用的模型，优先级：环境变量 > 参数 > 默认值。"""
        import os

        from nanobot.config.schema import Config

        # 1. 环境变量优先
        env_model = os.environ.get("NANOBOT_SUMMARY_MODEL")
        if env_model:
            return env_model

        # 2. 参数优先
        if model:
            return model

        # 3. 配置文件
        try:
            config = Config()
            if config.agents.summary.model:
                return config.agents.summary.model
            # 回退到默认模型
            if config.agents.defaults.model:
                return config.agents.defaults.model
        except Exception:
            pass

        # 4. 默认值
        return "deepseek/deepseek-chat"

    async def summarize_today(self) -> DailySummary:
        """生成今日对话概要"""
        logger.debug(f"Starting daily summarization for {datetime.now().strftime('%Y-%m-%d')}")

        # 1. 读取今天的所有会话文件
        today_messages = self._get_today_messages()

        if not today_messages:
            logger.warning(f"No messages found for {datetime.now().strftime('%Y-%m-%d')}")
            return DailySummary(
                date=datetime.now().strftime("%Y-%m-%d"),
                topics=[],
                user_preferences={},
                decisions=[],
                tasks=[],
                technical_issues=[],
                key_insights=["今日无对话记录"],
            )

        # 2. 提取各类信息
        topics = self._extract_topics(today_messages)
        preferences = self._extract_preferences(today_messages)
        decisions = self._extract_decisions(today_messages)
        tasks = self._extract_tasks(today_messages)
        technical_issues = self._extract_technical(today_messages)
        insights = self._generate_insights(today_messages)

        # 3. 生成每日概要
        summary = DailySummary(
            date=datetime.now().strftime("%Y-%m-%d"),
            topics=topics,
            user_preferences=preferences,
            decisions=decisions,
            tasks=tasks,
            technical_issues=technical_issues,
            key_insights=insights,
        )

        # 4. 格式化并保存
        summary_markdown = self._format_daily_summary(summary)
        self._save_daily_summary(summary_markdown)

        logger.debug("Daily summary generated successfully")
        return summary

    def _get_today_messages(self) -> list[dict[str, Any]]:
        """读取今天的所有会话消息"""
        messages = []

        # 遍历所有会话文件，查找今天的消息
        for session_file in self.sessions_dir.glob("*.jsonl"):
            try:
                content = session_file.read_text(encoding="utf-8")

                # 解析 JSONL 格式
                for line in content.strip().split("\n"):
                    if not line:
                        continue

                    try:
                        msg = json.loads(line)

                        # 检查消息是否是今天
                        if self._is_message_from_today(msg):
                            messages.append(msg)
                    except Exception as e:
                        logger.warning(f"Failed to parse message: {e}")

            except Exception as e:
                logger.error(f"Failed to read session file {session_file}: {e}")

        return messages

    def _is_message_from_today(self, msg: dict[str, Any]) -> bool:
        """判断消息是否来自今天"""
        if "timestamp" not in msg:
            return False

        try:
            msg_date = datetime.fromisoformat(msg["timestamp"])
            today = datetime.now().date()
            return msg_date.date() == today
        except Exception:
            return True

    def _extract_topics(self, messages: list[dict[str, Any]]) -> list[str]:
        """提取对话话题"""
        topics = []

        # 简单的话题聚类：统计不同对话中的关键词
        user_messages = [m for m in messages if m.get("role") == "user"]

        # 统计高频词汇
        from collections import Counter

        word_counter = Counter()

        for msg in user_messages:
            content = msg.get("content", "")
            # 分词并统计
            words = self._tokenize(content)
            word_counter.update(words)

        # 提取前 5 个高频词作为潜在话题
        common_words = word_counter.most_common(5)
        topics.extend([word for word, count in common_words])

        return list(set(topics))[:5]  # 最多 5 个话题

    def _tokenize(self, text: str) -> list[str]:
        """简单的中文分词"""
        import re

        # 简单的中文词提取（按标点和空格分）
        tokens = re.findall(r"[\w\u4e00-\u9fa5]+", text)
        return tokens

    def _extract_preferences(self, messages: list[dict[str, Any]]) -> dict[str, str]:
        """提取用户偏好"""
        preferences = {}
        preference_keywords = ["喜欢", "偏好", "希望", "风格", "习惯", "想要", "需要"]

        # 只处理用户消息
        user_messages = [m for m in messages if m.get("role") == "user"]

        for msg in user_messages:
            content = msg.get("content", "")

            # 检查是否包含任何偏好关键词
            if any(keyword in content for keyword in preference_keywords):
                # 使用完整消息（最多 100 字符）
                preference_text = content[:100] if len(content) > 100 else content

                # 根据内容选择最合适的关键词
                for keyword in preference_keywords:
                    if keyword in content:
                        if keyword not in preferences:
                            preferences[keyword] = preference_text
                        break

        return preferences

    def _extract_decisions(self, messages: list[dict[str, Any]]) -> list[str]:
        """提取重要决定"""
        decisions = []
        decision_keywords = ["决定", "选择", "采用", "方案", "计划", "确认", "将"]

        # 只处理用户消息
        user_messages = [m for m in messages if m.get("role") == "user"]

        for msg in user_messages:
            content = msg.get("content", "")

            # 检查是否包含决定关键词
            if any(keyword in content for keyword in decision_keywords):
                # 使用完整消息（最多 100 字符）
                decision_text = content[:100] if len(content) > 100 else content

                # 去重
                if decision_text not in decisions:
                    decisions.append(decision_text)

        return list(set(decisions))[:10]

    def _extract_tasks(self, messages: list[dict[str, Any]]) -> list[str]:
        """提取待办事项"""
        tasks = []

        # 只处理用户消息
        user_messages = [m for m in messages if m.get("role") == "user"]

        for msg in user_messages:
            content = msg.get("content", "")

            # 检查是否包含动词（通常任务包含动词）
            task_verbs = [
                "实现",
                "开发",
                "编写",
                "创建",
                "修复",
                "更新",
                "测试",
                "安装",
                "配置",
                "添加",
                "删除",
                "部署",
            ]

            if any(verb in content for verb in task_verbs):
                # 使用完整消息（最多 100 字符）
                task_text = content[:100] if len(content) > 100 else content

                # 去重
                if task_text not in tasks:
                    tasks.append(task_text)

        return list(set(tasks))[:10]  # 最多 10 个任务

    def _extract_technical(self, messages: list[dict[str, Any]]) -> list[dict]:
        """提取技术问题和解决方案"""
        issues = []

        problem_keywords = ["问题", "错误", "bug", "失败", "异常", "不能", "无法"]

        # 只处理用户消息
        user_messages = [m for m in messages if m.get("role") == "user"]

        for msg in user_messages:
            content = msg.get("content", "")

            # 检查是否包含问题关键词
            has_problem = any(keyword in content for keyword in problem_keywords)
            if not has_problem:
                continue

            # 使用完整消息作为问题描述（最多 100 字符）
            problem_text = content[:100] if len(content) > 100 else content

            # 查找解决方案（在助手回复中）
            assistant_replies = [m for m in messages if m.get("role") == "assistant"]
            solution_text = "未找到解决方案"

            for reply in assistant_replies:
                if reply.get("content", "") in assistant_replies:
                    reply_content = reply.get("content", "")
                    solution_keywords = [
                        "解决",
                        "修复",
                        "方法",
                        "方案",
                        "配置",
                        "设置",
                        "安装",
                        "更新",
                    ]

                    if any(keyword in reply_content for keyword in solution_keywords):
                        solution_text = (
                            reply_content[:100] if len(reply_content) > 100 else reply_content
                        )
                        break

            # 去重（使用问题文本作为唯一标识）
            issue_key = problem_text[:50]
            if issue_key not in [i.get("question", "")[:50] for i in issues]:
                issues.append(
                    {
                        "question": problem_text,
                        "solution": solution_text,
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return issues[:5]  # 最多 5 个问题

    def _generate_insights(self, messages: list[dict[str, Any]]) -> list[str]:
        """生成关键洞察"""
        insights = []

        # 简单的洞察提取
        if len(messages) == 0:
            insights.append("今日无对话")
        else:
            user_count = len([m for m in messages if m.get("role") == "user"])

            if user_count > 20:
                insights.append(f"今日有 {user_count} 条用户消息，对话较为活跃")
            elif user_count > 5:
                insights.append(f"今日有 {user_count} 条用户消息，有一定交互")
            else:
                insights.append(f"今日有 {user_count} 条用户消息，交互较少")

        # 检查是否有技术问题
        has_issues = any("错误" in m.get("content", "") for m in messages)
        if has_issues:
            insights.append("对话中遇到一些技术问题")

        return insights[:3]

    def _format_daily_summary(self, summary: DailySummary) -> str:
        """格式化每日概要为 Markdown"""
        lines = []

        lines.append(f"# 对话概要 - {summary.date}")
        lines.append("")

        # 主要话题
        if summary.topics:
            lines.append("## 📌 主要话题")
            for i, topic in enumerate(summary.topics, 1):
                lines.append(f"{i}. {topic}")
            lines.append("")

        # 用户偏好
        if summary.user_preferences:
            lines.append("## 👤 用户偏好")
            for key, value in summary.user_preferences.items():
                lines.append(f"- **{key}**: {value}")
            lines.append("")

        # 重要决定
        if summary.decisions:
            lines.append("## ✅ 重要决定")
            for decision in summary.decisions:
                lines.append(f"- {decision}")
            lines.append("")

        # 待办事项
        if summary.tasks:
            lines.append("## 📋 待办事项")
            for i, task in enumerate(summary.tasks, 1):
                lines.append(f"{i}. {task}")
            lines.append("")

        # 技术问题
        if summary.technical_issues:
            lines.append("## 🔧 技术问题与解决")
            for i, issue in enumerate(summary.technical_issues, 1):
                lines.append(f"### 问题 {i + 1}")
                lines.append(f"**问题**: {issue['question']}")
                lines.append(f"**解决**: {issue['solution']}")
                lines.append(f"**时间**: {issue['timestamp']}")
                lines.append("")

        # 关键洞察
        if summary.key_insights:
            lines.append("## 💡 关键洞察")
            for insight in summary.key_insights:
                lines.append(f"- {insight}")
            lines.append("")

        # 生成时间戳
        lines.append("")
        lines.append(f"*自动生成于 {datetime.now().strftime('%H:%M')}*")
        lines.append("")

        return "\n".join(lines)

    def _save_daily_summary(self, content: str) -> None:
        """保存每日概要文件"""
        today_str = datetime.now().strftime("%Y-%m-%d")
        summary_file = self.memory_dir / f"{today_str}.md"

        try:
            # 追加模式：如果文件存在，先读取并追加
            if summary_file.exists():
                existing_content = summary_file.read_text(encoding="utf-8")
                content = existing_content + "\n\n" + content
            else:
                content = content

            summary_file.write_text(content, encoding="utf-8")
            logger.debug(f"Daily summary saved to {summary_file}")
        except Exception as e:
            logger.error(f"Failed to save daily summary: {e}")
