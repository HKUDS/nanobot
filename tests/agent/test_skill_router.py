"""Tests for nanobot.agent.skill_router — BM25-lite skill routing."""

from __future__ import annotations

import pytest

from nanobot.agent.skill_router import SkillRouter, extract_skill_keywords, tokenize


# ---------------------------------------------------------------------------
# Tokenizer tests
# ---------------------------------------------------------------------------


class TestTokenize:
    def test_english_words(self):
        tokens = tokenize("Help me review a PR")
        assert "help" in tokens
        assert "me" in tokens
        assert "review" in tokens
        assert "pr" in tokens
        # 'a' is a single letter, won't match [A-Za-z][A-Za-z0-9_-]+
        assert len(tokens) == 4

    def test_chinese_characters(self):
        tokens = tokenize("帮我看看那个PR")
        # Chinese is now bigram-tokenized (2-char chunks)
        assert "帮我" in tokens
        assert "看看" in tokens
        assert "那个" in tokens
        assert "pr" in tokens

    def test_mixed_language(self):
        tokens = tokenize("把 SVG 渲染成 PNG")
        assert "svg" in tokens
        assert "png" in tokens
        # Chinese characters tokenized as bigrams
        assert "渲染" in tokens

    def test_numbers(self):
        tokens = tokenize("test with 3 files")
        assert "3" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_punctuation_dropped(self):
        tokens = tokenize("hello, world!")
        assert "hello" in tokens
        assert "world" in tokens
        assert "," not in tokens
        assert "!" not in tokens


# ---------------------------------------------------------------------------
# SkillRouter tests
# ---------------------------------------------------------------------------

_SAMPLE_SKILLS = [
    {
        "name": "github",
        "path": "/skills/github/SKILL.md",
        "description": "Interact with GitHub using gh CLI. Issues, PRs, CI runs.",
        "triggers": ["pr", "issue", "merge", "ci", "pull request"],
    },
    {
        "name": "weather",
        "path": "/skills/weather/SKILL.md",
        "description": "Get current weather and forecasts. No API key required.",
        "triggers": ["temperature", "forecast", "rain", "天气", "温度", "预报"],
    },
    {
        "name": "summarize",
        "path": "/skills/summarize/SKILL.md",
        "description": "Summarize URLs, podcasts, transcripts. Transcribe YouTube videos.",
        "triggers": ["youtube", "transcript", "summary", "podcast", "总结", "摘要"],
    },
    {
        "name": "image-generation",
        "path": "/skills/image-generation/SKILL.md",
        "description": "Generate images and iteratively edit saved image artifacts.",
        "triggers": ["generate", "image", "picture", "draw", "生成", "图片", "画"],
    },
    {
        "name": "skill-creator",
        "path": "/skills/skill-creator/SKILL.md",
        "description": "Create or update AgentSkills with scripts, references, and assets.",
        "triggers": ["skill", "create", "package"],
    },
    {
        "name": "tmux",
        "path": "/skills/tmux/SKILL.md",
        "description": "Remote-control tmux sessions for interactive CLIs.",
        "triggers": ["terminal", "session"],
    },
]


class TestSkillRouter:
    def test_route_github_pr(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("帮我看看那个 PR 的 CI 有没有过", top_k=3)
        names = [r["name"] for r in results]
        assert "github" in names
        assert results[0]["name"] == "github"  # Should be top-ranked

    def test_route_weather(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("今天天气怎么样", top_k=3)
        names = [r["name"] for r in results]
        assert "weather" in names

    def test_route_summarize_video(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("帮我总结这个 YouTube 视频", top_k=3)
        names = [r["name"] for r in results]
        assert "summarize" in names

    def test_route_image_generation(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("帮我生成一张猫咪图片", top_k=3)
        names = [r["name"] for r in results]
        assert "image-generation" in names

    def test_route_empty_query_returns_all(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("", top_k=5)
        assert len(results) == len(_SAMPLE_SKILLS)  # Fallback: all skills

    def test_route_exact_name_bonus(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("github", top_k=3)
        assert results[0]["name"] == "github"

    def test_top_k_limits_results(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("帮我看看 PR", top_k=2)
        assert len(results) <= 2

    def test_always_skills_included(self):
        always = {"weather"}
        router = SkillRouter(_SAMPLE_SKILLS, always_skills=always)
        results = router.route("帮我看看 PR", top_k=2)
        names = [r["name"] for r in results]
        assert "weather" in names  # Always included
        # The always skill should have score=-1
        weather_entry = next(r for r in results if r["name"] == "weather")
        assert weather_entry["score"] == -1.0

    def test_scores_are_floats(self):
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("PR review", top_k=3)
        for r in results:
            assert isinstance(r["score"], float)

    def test_pure_chinese_no_match_fallback(self):
        """Pure Chinese query with no matching Chinese triggers returns empty (below min_score)."""
        router = SkillRouter(_SAMPLE_SKILLS)
        results = router.route("今天天气怎么样", top_k=3, min_score=0.05)
        # "天气" is in weather's triggers, so it should match
        names = [r["name"] for r in results]
        assert "weather" in names

    def test_no_skills_returns_empty(self):
        router = SkillRouter([])
        results = router.route("hello", top_k=5)
        assert results == []

    def test_chinese_trigger_routing(self):
        """Chinese trigger words enable cross-language routing."""
        skills = [
            {
                "name": "github",
                "path": "/skills/github/SKILL.md",
                "description": "Interact with GitHub using gh CLI.",
                "triggers": ["代码", "仓库", "提交"],
            },
        ]
        router = SkillRouter(skills)
        results = router.route("帮我看看代码仓库", top_k=3)
        assert len(results) == 1
        assert results[0]["name"] == "github"


# ---------------------------------------------------------------------------
# extract_skill_keywords tests
# ---------------------------------------------------------------------------


class TestExtractSkillKeywords:
    def test_trigger_string(self):
        fm = {"trigger": "pr, issue, merge"}
        kw = extract_skill_keywords(fm)
        assert "pr" in kw
        assert "issue" in kw
        assert "merge" in kw

    def test_triggers_list(self):
        fm = {"triggers": ["weather", "forecast"]}
        kw = extract_skill_keywords(fm)
        assert "weather" in kw
        assert "forecast" in kw

    def test_keywords_field(self):
        fm = {"keywords": "image, generate, picture"}
        kw = extract_skill_keywords(fm)
        assert "image" in kw

    def test_no_keywords(self):
        fm = {"description": "A skill"}
        kw = extract_skill_keywords(fm)
        assert kw == []

    def test_aliases_field(self):
        fm = {"aliases": ["yt", "youtube-dl"]}
        kw = extract_skill_keywords(fm)
        assert "yt" in kw
        assert "youtube-dl" in kw
