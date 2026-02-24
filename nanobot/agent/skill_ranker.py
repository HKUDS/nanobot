"""Smart skill injection: rank skills by relevance to user query.

Uses lightweight TF-IDF (pure Python, zero dependencies) to match
user messages against skill content, injecting only the most relevant
skills into the system prompt.
"""

import math
import re
from collections import Counter
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nanobot.agent.skills import SkillsLoader

# CJK Unicode ranges for Chinese/Japanese/Korean tokenization
_CJK_RANGES = (
    "\u4e00-\u9fff"    # CJK Unified Ideographs
    "\u3400-\u4dbf"    # CJK Extension A
    "\U00020000-\U0002a6df"  # CJK Extension B
    "\uf900-\ufaff"    # CJK Compatibility Ideographs
)
_CJK_PATTERN = re.compile(f"[{_CJK_RANGES}]")
_WORD_PATTERN = re.compile(r"[a-zA-Z0-9_\-]+")

# Keyword aliases: map common terms to canonical forms for better matching
_KEYWORD_ALIASES: dict[str, list[str]] = {
    "search": ["搜索", "搜一下", "查一下", "查找", "检索", "searxng"],
    "github": ["gh", "仓库", "repo", "issue", "pr", "pull request", "star"],
    "weather": ["天气", "气温", "下雨", "下雪", "温度"],
    "browser": ["浏览器", "网页", "打开网站", "截图"],
    "code-review": ["代码审查", "review", "审查代码", "cr"],
    "debug": ["调试", "排错", "报错", "bug", "错误"],
    "cron": ["定时", "提醒", "闹钟", "定时任务", "schedule", "reminder"],
    "monitor": ["监控", "状态", "在干什么", "claude code"],
    "heartbeat": ["心跳", "检查", "巡检", "状态检查"],
    "memory": ["记住", "记忆", "记录"],
    "tmux": ["终端", "pane", "session", "窗口"],
    "image": ["图片", "生成图", "画图", "图像"],
}


def _tokenize(text: str) -> list[str]:
    """Tokenize text into words. Handles both English and CJK."""
    text = text.lower()
    tokens = []
    tokens.extend(_WORD_PATTERN.findall(text))
    cjk_chars = _CJK_PATTERN.findall(text)
    tokens.extend(cjk_chars)
    for i in range(len(cjk_chars) - 1):
        tokens.append(cjk_chars[i] + cjk_chars[i + 1])
    return tokens


def _expand_aliases(tokens: list[str]) -> list[str]:
    """Expand tokens with keyword aliases for cross-language matching."""
    expanded = list(tokens)
    text_joined = " ".join(tokens)
    for canonical, aliases in _KEYWORD_ALIASES.items():
        matched = canonical in text_joined or any(a in text_joined for a in aliases)
        if matched:
            expanded.append(canonical)
            expanded.extend(aliases)
    return expanded


def _tf(tokens: list[str]) -> dict[str, float]:
    """Term frequency (normalized)."""
    counts = Counter(tokens)
    total = len(tokens) or 1
    return {t: c / total for t, c in counts.items()}


def _idf(doc_token_sets: list[set[str]], vocab: set[str]) -> dict[str, float]:
    """Inverse document frequency."""
    n = len(doc_token_sets) or 1
    idf = {}
    for term in vocab:
        df = sum(1 for doc in doc_token_sets if term in doc)
        idf[term] = math.log((n + 1) / (df + 1)) + 1  # smoothed IDF
    return idf


def _cosine_sim(vec_a: dict[str, float], vec_b: dict[str, float]) -> float:
    """Cosine similarity between two sparse vectors."""
    common = set(vec_a) & set(vec_b)
    if not common:
        return 0.0
    dot = sum(vec_a[k] * vec_b[k] for k in common)
    norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
    norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class SkillRanker:
    """Ranks skills by relevance to a user query using TF-IDF."""

    def __init__(self, skills_loader: "SkillsLoader"):
        self._loader = skills_loader
        self._docs: dict[str, list[str]] = {}
        self._idf: dict[str, float] = {}
        self._tfidf_vecs: dict[str, dict[str, float]] = {}
        self._built = False

    def _build_index(self) -> None:
        """Build TF-IDF index from all available skills."""
        all_skills = self._loader.list_skills(filter_unavailable=True)
        if not all_skills:
            self._built = True
            return

        for s in all_skills:
            name = s["name"]
            desc = self._loader._get_skill_description(name)
            content = self._loader.load_skill(name) or ""
            doc_text = f"{name} {name} {name} {desc} {desc} {content}"
            tokens = _tokenize(doc_text)
            self._docs[name] = _expand_aliases(tokens)

        doc_sets = [set(tokens) for tokens in self._docs.values()]
        vocab: set[str] = set()
        for s in doc_sets:
            vocab.update(s)
        self._idf = _idf(doc_sets, vocab)

        for name, tokens in self._docs.items():
            tf = _tf(tokens)
            self._tfidf_vecs[name] = {
                t: tf_val * self._idf.get(t, 1.0)
                for t, tf_val in tf.items()
            }

        self._built = True
        logger.debug(f"SkillRanker: indexed {len(self._docs)} skills")

    def rank(self, query: str, top_k: int = 3, threshold: float = 0.05) -> list[tuple[str, float]]:
        """Rank skills by relevance to query."""
        if not self._built:
            self._build_index()
        if not self._tfidf_vecs:
            return []

        q_tokens = _expand_aliases(_tokenize(query))
        if not q_tokens:
            return []

        q_tf = _tf(q_tokens)
        q_vec = {t: tf_val * self._idf.get(t, 1.0) for t, tf_val in q_tf.items()}

        scores = []
        for name, doc_vec in self._tfidf_vecs.items():
            sim = _cosine_sim(q_vec, doc_vec)
            if sim >= threshold:
                scores.append((name, sim))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def get_relevant_skills(
        self,
        query: str,
        always_skills: list[str],
        top_k: int = 3,
        threshold: float = 0.05,
    ) -> tuple[list[str], list[str]]:
        """Get skills to inject: always + top-K relevant."""
        ranked = self.rank(query, top_k=top_k, threshold=threshold)
        ranked_names = [name for name, _ in ranked]

        inject = list(always_skills)
        for name in ranked_names:
            if name not in inject:
                inject.append(name)

        all_names = [s["name"] for s in self._loader.list_skills(filter_unavailable=True)]
        summary_only = [n for n in all_names if n not in inject]

        if ranked_names:
            logger.info(f"SkillRanker: injecting {ranked_names} (scores: {[f'{s:.3f}' for _, s in ranked]})")

        return inject, summary_only
