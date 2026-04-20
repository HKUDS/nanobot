"""技能加载器，用于管理Agent的能力。

功能说明：
1. 加载和管理Skill（技能）文件
2. Skill是markdown文件(SKILL.md)，教导Agent如何使用特定工具或执行任务
3. 支持内置技能和工作区自定义技能
4. 支持技能依赖检查（CLI命令、环境变量等）
5. 支持技能的渐进式加载

Skill文件格式：
- 每个技能一个目录，包含SKILL.md文件
- SKILL.md使用YAML frontmatter定义元数据
- 支持metadata字段：description(描述)、always(是否始终加载)、requires(依赖要求)
"""

import json
import os
import re
import shutil
from pathlib import Path

import yaml

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"

# Opening ---, YAML body (group 1), closing --- on its own line; supports CRLF.
_STRIP_SKILL_FRONTMATTER = re.compile(
    r"^---\s*\r?\n(.*?)\r?\n---\s*\r?\n?",
    re.DOTALL,
)


class SkillsLoader:
    """Agent技能加载器。
    
    Skills是markdown文件(SKILL.md)，用于教导Agent如何使用特定工具或执行任务。
    支持从两个来源加载技能：
    - 工作区skills目录（用户自定义）
    - 内置skills目录（预置技能）
    
    属性：
    - workspace: 工作区根目录
    - workspace_skills: 工作区技能目录
    - builtin_skills: 内置技能目录
    - disabled_skills: 禁用的技能集合
    """

    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None, disabled_skills: set[str] | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
        self.disabled_skills = disabled_skills or set()

    def _skill_entries_from_dir(self, base: Path, source: str, *, skip_names: set[str] | None = None) -> list[dict[str, str]]:
        """从指定目录扫描并收集所有技能条目。
        
        Args:
            base: 技能目录根路径
            source: 技能来源标识（'workspace' 或 'builtin'）
            skip_names: 需要跳过的技能名称集合
            
        Returns:
            技能信息字典列表，每项包含'name', 'path', 'source'
        """
        if not base.exists():
            return []
        entries: list[dict[str, str]] = []
        for skill_dir in base.iterdir():
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                continue
            name = skill_dir.name
            if skip_names is not None and name in skip_names:
                continue
            entries.append({"name": name, "path": str(skill_file), "source": source})
        return entries

    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """列出所有可用的技能。
        
        Args:
            filter_unavailable: 是否过滤掉不满足依赖要求的技能
            
        Returns:
            技能信息字典列表，每项包含'name', 'path', 'source'
        """
        skills = self._skill_entries_from_dir(self.workspace_skills, "workspace")
        workspace_names = {entry["name"] for entry in skills}
        if self.builtin_skills and self.builtin_skills.exists():
            skills.extend(
                self._skill_entries_from_dir(self.builtin_skills, "builtin", skip_names=workspace_names)
            )

        if self.disabled_skills:
            skills = [s for s in skills if s["name"] not in self.disabled_skills]

        if filter_unavailable:
            return [skill for skill in skills if self._check_requirements(self._get_skill_meta(skill["name"]))]
        return skills

    def load_skill(self, name: str) -> str | None:
        """根据名称加载技能。
        
        按优先级搜索：工作区技能 -> 内置技能
        
        Args:
            name: 技能名称（目录名）
            
        Returns:
            技能内容，如果未找到则返回None
        """
        roots = [self.workspace_skills]
        if self.builtin_skills:
            roots.append(self.builtin_skills)
        for root in roots:
            path = root / name / "SKILL.md"
            if path.exists():
                return path.read_text(encoding="utf-8")
        return None

    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """为Agent上下文加载指定的技能。
        
        加载多个技能并格式化为连续的markdown内容。
        
        Args:
            skill_names: 要加载的技能名称列表
            
        Returns:
            格式化的技能内容
        """
        parts = [
            f"### Skill: {name}\n\n{self._strip_frontmatter(markdown)}"
            for name in skill_names
            if (markdown := self.load_skill(name))
        ]
        return "\n\n---\n\n".join(parts)

    def build_skills_summary(self, exclude: set[str] | None = None) -> str:
        """构建所有技能的摘要（名称、描述、路径、可用性）。
        
        用于渐进式加载 - Agent需要时可以使用read_file读取完整技能内容。
        
        Args:
            exclude: 要从摘要中排除的技能名称集合
            
        Returns:
            Markdown格式的技能摘要
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""

        lines: list[str] = []
        for entry in all_skills:
            skill_name = entry["name"]
            if exclude and skill_name in exclude:
                continue
            meta = self._get_skill_meta(skill_name)
            available = self._check_requirements(meta)
            desc = self._get_skill_description(skill_name)
            if available:
                lines.append(f"- **{skill_name}** — {desc}  `{entry['path']}`")
            else:
                missing = self._get_missing_requirements(meta)
                suffix = f" (unavailable: {missing})" if missing else " (unavailable)"
                lines.append(f"- **{skill_name}** — {desc}{suffix}  `{entry['path']}`")
        return "\n".join(lines)

    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """获取缺失的依赖要求描述。
        
        Args:
            skill_meta: 技能的元数据字典
            
        Returns:
            格式化的缺失依赖描述字符串
        """
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return ", ".join(
            [f"CLI: {command_name}" for command_name in required_bins if not shutil.which(command_name)]
            + [f"ENV: {env_name}" for env_name in required_env_vars if not os.environ.get(env_name)]
        )

    def _get_skill_description(self, name: str) -> str:
        """从技能的frontmatter中获取技能描述。
        
        Args:
            name: 技能名称
            
        Returns:
            技能描述，如果未找到则返回技能名称作为后备
        """
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name

    def _strip_frontmatter(self, content: str) -> str:
        """从markdown内容中移除YAML frontmatter。
        
        Args:
            content: 包含frontmatter的markdown内容
            
        Returns:
            移除frontmatter后的markdown内容
        """
        if not content.startswith("---"):
            return content
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if match:
            return content[match.end():].strip()
        return content

    def _parse_nanobot_metadata(self, raw: object) -> dict:
        """从frontmatter字段中提取nanobot/openclaw元数据。
        
        Args:
            raw: 原始元数据，可以是dict或JSON字符串
            
        Returns:
            解析后的nanobot/openclaw元数据字典
        """
        if isinstance(raw, dict):
            data = raw
        elif isinstance(raw, str):
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        else:
            return {}
        if not isinstance(data, dict):
            return {}
        payload = data.get("nanobot", data.get("openclaw", {}))
        return payload if isinstance(payload, dict) else {}

    def _check_requirements(self, skill_meta: dict) -> bool:
        """检查技能的依赖要求是否满足（CLI命令、环境变量）。
        
        Args:
            skill_meta: 技能的元数据字典
            
        Returns:
            所有依赖都满足返回True，否则返回False
        """
        requires = skill_meta.get("requires", {})
        required_bins = requires.get("bins", [])
        required_env_vars = requires.get("env", [])
        return all(shutil.which(cmd) for cmd in required_bins) and all(
            os.environ.get(var) for var in required_env_vars
        )

    def _get_skill_meta(self, name: str) -> dict:
        """获取技能的nanobot元数据（从frontmatter中提取）。
        
        Args:
            name: 技能名称
            
        Returns:
            nanobot元数据字典
        """
        raw_meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(raw_meta.get("metadata"))

    def get_always_skills(self) -> list[str]:
        """获取标记为always=true且满足依赖要求的技能列表。
        
        Returns:
            需要始终加载的技能名称列表
        """
        return [
            entry["name"]
            for entry in self.list_skills(filter_unavailable=True)
            if (meta := self.get_skill_metadata(entry["name"]) or {})
            and (
                self._parse_nanobot_metadata(meta.get("metadata")).get("always")
                or meta.get("always")
            )
        ]

    def get_skill_metadata(self, name: str) -> dict | None:
        """从技能的frontmatter中获取元数据。
        
        Args:
            name: 技能名称
            
        Returns:
            元数据字典，如果未找到则返回None
        """
        content = self.load_skill(name)
        if not content or not content.startswith("---"):
            return None
        match = _STRIP_SKILL_FRONTMATTER.match(content)
        if not match:
            return None
        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None
        if not isinstance(parsed, dict):
            return None
        # yaml.safe_load returns native types (int, bool, list, etc.);
        # keep values as-is so downstream consumers get correct types.
        metadata: dict[str, object] = {}
        for key, value in parsed.items():
            metadata[str(key)] = value
        return metadata
