"""记忆更新器 - 智能更新长期记忆。"""

from pathlib import Path
from typing import Any

from nanobot import logger


class MemoryUpdater:
    """记忆更新器 - 智能更新长期记忆。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.memory_file = workspace / "memory" / "MEMORY.md"

        # 去重相似度阈值（默认 80%）
        self.similarity_threshold = 0.8

        # 最大记忆条目数（默认 100）
        self.max_memory_items = 100

    def update_long_term(self, summary: Any) -> None:
        """根据概要更新长期记忆"""
        logger.info("Starting long-term memory update")

        # 1. 读取现有记忆
        try:
            existing_content = self.memory_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read existing memory: {e}")
            existing_content = ""

        # 2. 提取需要记录的信息
        new_items = self._extract_items_from_summary(summary)

        # 3. 去重
        unique_items = self._deduplicate_with_memory(new_items, existing_content)

        # 4. 追加新内容到长期记忆
        if unique_items:
            new_content = existing_content + "\n\n" + "\n".join(unique_items)
            self.memory_file.write_text(new_content, encoding="utf-8")
            logger.info(f"Updated long-term memory with {len(unique_items)} new items")
        else:
            logger.info("No new items to add to long-term memory")

    def _extract_items_from_summary(self, summary: Any) -> list[str]:
        """从概要中提取需要记录的信息"""
        items = []

        # 提取用户偏好
        if hasattr(summary, "user_preferences") and summary.user_preferences:
            for key, value in summary.user_preferences.items():
                items.append(f"**用户偏好** {key}: {value}")

        # 提取重要决定
        if hasattr(summary, "decisions") and summary.decisions:
            for decision in summary.decisions:
                items.append(f"**重要决定** {decision}")

        # 提取技术配置信息
        if hasattr(summary, "technical_issues") and summary.technical_issues:
            for issue in summary.technical_issues:
                items.append(
                    f"**技术问题** {issue.get('question', '')} - {issue.get('solution', '')}"
                )

        return items

    def _deduplicate_with_memory(self, new_items: list[str], existing: str) -> list[str]:
        """去重：移除与现有记忆相似的信息"""
        unique_items = []

        for item in new_items:
            # 检查是否与现有记忆相似
            if self._is_similar_to_existing(item, existing):
                logger.debug(f"Skipping duplicate item: {item[:50]}")
                continue
            unique_items.append(item)

        return unique_items

    def _is_similar_to_existing(self, item: str, existing: str) -> bool:
        """判断信息是否与现有记忆相似"""
        # 简单实现：检查新信息是否是现有内容的子串
        # 使用小写比较，忽略空格
        item_lower = item.lower().strip()
        existing_lower = existing.lower()

        return item_lower in existing_lower

    def _should_update_memory(self, info: str) -> bool:
        """判断信息是否应该被记录到长期记忆"""
        importance = self._calculate_importance(info)
        return importance >= 2  # 阈值 2 分及以上为重要

    def _calculate_importance(self, info: str) -> int:
        """计算信息的重要性分数"""
        score = 0

        info_lower = info.lower()

        # 用户明确要求记录（最高优先级）
        if any(keyword in info_lower for keyword in ["记住", "记录", "请记住", "重要", "必须记得"]):
            score += 3

        # 配置信息（高优先级）
        if any(
            keyword in info_lower for keyword in ["api", "配置", "密钥", "设置", "token", "模型"]
        ):
            score += 2

        # 用户偏好（中优先级）
        if any(
            keyword in info_lower for keyword in ["喜欢", "偏好", "习惯", "风格", "想要", "需要"]
        ):
            score += 1

        # 技术问题解决方案（高优先级）
        if any(keyword in info_lower for keyword in ["问题", "解决", "修复", "bug", "错误"]):
            score += 2

        return score

    def get_memory_content(self) -> str:
        """读取长期记忆内容"""
        try:
            return self.memory_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to read memory file: {e}")
            return ""

    def list_memory(self) -> list[str]:
        """列出长期记忆中的所有条目（每行一个）"""
        try:
            content = self.memory_file.read_text(encoding="utf-8")
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            return lines
        except Exception as e:
            logger.error(f"Failed to list memory items: {e}")
            return []
