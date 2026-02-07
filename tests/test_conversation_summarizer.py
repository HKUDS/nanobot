"""测试对话总结器功能。"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, AsyncMock

import pytest

from nanobot.agent.conversation_summarizer import (
    ConversationSummarizer,
    DailySummary,
    TechnicalIssue,
)


@pytest.fixture
def mock_provider():
    """模拟 LLM provider。"""
    provider = Mock()
    return provider


@pytest.fixture
def temp_workspace():
    """临时工作空间目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        memory_dir = workspace / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        yield workspace


@pytest.fixture
def summarizer(mock_provider, temp_workspace):
    """创建 ConversationSummarizer 实例。"""
    return ConversationSummarizer(temp_workspace, mock_provider)


@pytest.fixture
def sample_messages():
    """示例消息数据。"""
    return [
        {"role": "user", "content": "我喜欢简洁的代码风格", "timestamp": "2026-02-07T10:00:00"},
        {
            "role": "assistant",
            "content": "好的，我会注意代码风格",
            "timestamp": "2026-02-07T10:01:00",
        },
        {"role": "user", "content": "我们需要实现一个新的功能", "timestamp": "2026-02-07T10:05:00"},
        {
            "role": "assistant",
            "content": "明白了，我来帮你实现",
            "timestamp": "2026-02-07T10:06:00",
        },
        {"role": "user", "content": "有个错误需要修复", "timestamp": "2026-02-07T10:10:00"},
        {"role": "assistant", "content": "解决方案是更新依赖", "timestamp": "2026-02-07T10:11:00"},
    ]


def test_daily_summary_dataclass():
    """测试 DailySummary 数据类。"""
    summary = DailySummary(
        date="2026-02-07",
        topics=["代码风格", "功能实现"],
        user_preferences={"简洁": "简洁的代码风格"},
        decisions=["实现新功能"],
        tasks=["修复错误"],
        technical_issues=[],
        key_insights=["对话活跃"],
    )

    assert summary.date == "2026-02-07"
    assert len(summary.topics) == 2
    assert len(summary.user_preferences) == 1


def test_technical_issue_dataclass():
    """测试 TechnicalIssue 数据类。"""
    issue = TechnicalIssue(
        question="无法连接数据库", solution="检查配置文件", timestamp="2026-02-07T10:00:00"
    )

    assert issue.question == "无法连接数据库"
    assert issue.solution == "检查配置文件"


def test_extract_topics(summarizer, sample_messages):
    """测试话题提取功能。"""
    topics = summarizer._extract_topics(sample_messages)

    assert isinstance(topics, list)
    assert len(topics) <= 5
    assert all(isinstance(topic, str) for topic in topics)


def test_extract_preferences(summarizer, sample_messages):
    """测试偏好提取功能。"""
    preferences = summarizer._extract_preferences(sample_messages)

    assert isinstance(preferences, dict)
    assert len(preferences) > 0
    # 检查是否包含完整消息（不再截断）
    for key, value in preferences.items():
        assert len(value) > 0


def test_extract_decisions(summarizer, sample_messages):
    """测试决定提取功能。"""
    decisions = summarizer._extract_decisions(sample_messages)

    assert isinstance(decisions, list)
    assert len(decisions) <= 10
    # 检查决定是否包含完整内容（不再截断）
    for decision in decisions:
        assert len(decision) > 0


def test_extract_tasks(summarizer, sample_messages):
    """测试任务提取功能。"""
    tasks = summarizer._extract_tasks(sample_messages)

    assert isinstance(tasks, list)
    assert len(tasks) <= 10


def test_extract_technical(summarizer, sample_messages):
    """测试技术问题提取功能。"""
    issues = summarizer._extract_technical(sample_messages)

    assert isinstance(issues, list)
    assert len(issues) <= 5
    for issue in issues:
        assert "question" in issue
        assert "solution" in issue
        assert "timestamp" in issue


def test_format_daily_summary(summarizer, sample_messages):
    """测试每日概要格式化功能。"""
    topics = summarizer._extract_topics(sample_messages)
    preferences = summarizer._extract_preferences(sample_messages)
    decisions = summarizer._extract_decisions(sample_messages)
    tasks = summarizer._extract_tasks(sample_messages)
    technical_issues = summarizer._extract_technical(sample_messages)
    insights = summarizer._generate_insights(sample_messages)

    summary = DailySummary(
        date="2026-02-07",
        topics=topics,
        user_preferences=preferences,
        decisions=decisions,
        tasks=tasks,
        technical_issues=technical_issues,
        key_insights=insights,
    )

    formatted = summarizer._format_daily_summary(summary)

    assert isinstance(formatted, str)
    assert "# 对话概要" in formatted
    assert "2026-02-07" in formatted


def test_get_model_with_env_var(summarizer, monkeypatch):
    """测试从环境变量获取模型。"""
    monkeypatch.setenv("NANOBOT_SUMMARY_MODEL", "gpt-4")

    model = summarizer._get_model(None)
    assert model == "gpt-4"

    monkeypatch.delenv("NANOBOT_SUMMARY_MODEL")


def test_get_model_with_param(summarizer):
    """测试从参数获取模型。"""
    model = summarizer._get_model("claude-3")
    assert model == "claude-3"


def test_get_model_default(summarizer, monkeypatch):
    """测试默认模型回退。"""
    # 移除所有可能影响模型选择的环境变量
    monkeypatch.delenv("NANOBOT_SUMMARY_MODEL", raising=False)

    model = summarizer._get_model(None)
    # 默认回退到配置中的 defaults.model 或硬编码默认值
    assert model is not None


def test_tokenize(summarizer):
    """测试中文分词功能。"""
    text = "我喜欢简洁的代码风格"
    tokens = summarizer._tokenize(text)

    assert isinstance(tokens, list)
    assert len(tokens) > 0
    # 分词结果是完整的句子（因为正则匹配整个中文/单词序列）
    assert len(tokens[0]) > 0


def test_save_daily_summary(summarizer, temp_workspace):
    """测试保存每日概要文件。"""
    content = "# 测试概要\n\n这是测试内容"

    summarizer._save_daily_summary(content)

    memory_dir = temp_workspace / "memory"
    summary_files = list(memory_dir.glob("*.md"))
    assert len(summary_files) > 0

    saved_content = summary_files[0].read_text(encoding="utf-8")
    assert "# 测试概要" in saved_content


@pytest.mark.asyncio
async def test_summarize_today_empty(summarizer, temp_workspace):
    """测试无消息时的总结。"""
    # 确保会话目录是空的（使用临时目录）
    temp_sessions_dir = temp_workspace / "test_sessions"
    temp_sessions_dir.mkdir(parents=True, exist_ok=True)
    summarizer.sessions_dir = temp_sessions_dir

    summary = await summarizer.summarize_today()

    assert summary is not None
    assert summary.topics == []
    assert "无对话" in summary.key_insights[0] or "无对话记录" in summary.key_insights[0]


def test_is_message_from_today(summarizer):
    """测试判断消息是否来自今天。"""
    from datetime import datetime, date

    today_msg = {"timestamp": datetime.now().isoformat()}

    old_msg = {"timestamp": "2026-01-01T10:00:00"}

    assert summarizer._is_message_from_today(today_msg) == True
    assert summarizer._is_message_from_today(old_msg) == False


def test_generate_insights(summarizer, sample_messages):
    """测试关键洞察生成。"""
    insights = summarizer._generate_insights(sample_messages)

    assert isinstance(insights, list)
    assert len(insights) <= 3
    assert all(isinstance(insight, str) for insight in insights)
