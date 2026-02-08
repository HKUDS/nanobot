"""Skills loader for agent capabilities."""

# 模块作用：技能加载器，管理AI代理的可扩展技能库
# 设计目的：通过Markdown文件定义技能，支持动态加载、需求检查和优先级管理
# 好处：技能与代码解耦，非技术人员可编写技能，支持条件启用和依赖检查
import json
import os
import re
import shutil
from pathlib import Path

# Default builtin skills directory (relative to this file)
BUILTIN_SKILLS_DIR = Path(__file__).parent.parent / "skills"


# 作用：技能加载器核心类，管理技能发现、加载和验证
# 设计目的：实现工作空间和内置技能的双层加载系统，支持需求检查和优先级
# 好处：灵活的技能管理，支持热更新，技能条件可用性检查
class SkillsLoader:
    """
    Loader for agent skills.
    
    Skills are markdown files (SKILL.md) that teach the agent how to use
    specific tools or perform certain tasks.
    """
    
    # 作用：初始化技能加载器，设置技能目录路径
    # 设计目的：支持自定义内置技能目录，优先加载工作空间技能
    # 好处：灵活的路径配置，便于测试和自定义技能部署
    def __init__(self, workspace: Path, builtin_skills_dir: Path | None = None):
        self.workspace = workspace
        self.workspace_skills = workspace / "skills"
        self.builtin_skills = builtin_skills_dir or BUILTIN_SKILLS_DIR
    
    # 作用：列出所有可用技能，支持按需求过滤
    # 设计目的：实现技能发现优先级（工作空间 > 内置），支持条件过滤
    # 好处：动态技能列表，自动过滤不可用技能，便于UI展示
    def list_skills(self, filter_unavailable: bool = True) -> list[dict[str, str]]:
        """
        List all available skills.
        
        Args:
            filter_unavailable: If True, filter out skills with unmet requirements.
        
        Returns:
            List of skill info dicts with 'name', 'path', 'source'.
        """
        skills = []
        
        # Workspace skills (highest priority)
        if self.workspace_skills.exists():
            for skill_dir in self.workspace_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "workspace"})
        
        # Built-in skills
        if self.builtin_skills and self.builtin_skills.exists():
            for skill_dir in self.builtin_skills.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists() and not any(s["name"] == skill_dir.name for s in skills):
                        skills.append({"name": skill_dir.name, "path": str(skill_file), "source": "builtin"})
        
        # Filter by requirements
        if filter_unavailable:
            return [s for s in skills if self._check_requirements(self._get_skill_meta(s["name"]))]
        return skills
    
    # 作用：按名称加载技能内容，支持优先级查找
    # 设计目的：优先查找工作空间技能，回退到内置技能
    # 好处：技能覆盖机制，支持自定义覆盖内置技能
    def load_skill(self, name: str) -> str | None:
        """
        Load a skill by name.
        
        Args:
            name: Skill name (directory name).
        
        Returns:
            Skill content or None if not found.
        """
        # Check workspace first
        workspace_skill = self.workspace_skills / name / "SKILL.md"
        if workspace_skill.exists():
            return workspace_skill.read_text(encoding="utf-8")
        
        # Check built-in
        if self.builtin_skills:
            builtin_skill = self.builtin_skills / name / "SKILL.md"
            if builtin_skill.exists():
                return builtin_skill.read_text(encoding="utf-8")
        
        return None
    
    # 作用：加载指定技能并格式化，用于智能体上下文
    # 设计目的：批量加载技能，移除frontmatter，添加技能标题分隔符
    # 好处：结构化技能内容，便于LLM理解和引用
    def load_skills_for_context(self, skill_names: list[str]) -> str:
        """
        Load specific skills for inclusion in agent context.
        
        Args:
            skill_names: List of skill names to load.
        
        Returns:
            Formatted skills content.
        """
        parts = []
        for name in skill_names:
            content = self.load_skill(name)
            if content:
                content = self._strip_frontmatter(content)
                parts.append(f"### Skill: {name}\n\n{content}")
        
        return "\n\n---\n\n".join(parts) if parts else ""
    
    # 作用：构建所有技能的XML摘要，包含可用性信息
    # 设计目的：渐进式加载支持，智能体先看摘要再决定加载完整技能
    # 好处：减少上下文长度，提高LLM效率，动态可用性标记
    def build_skills_summary(self) -> str:
        """
        Build a summary of all skills (name, description, path, availability).
        
        This is used for progressive loading - the agent can read the full
        skill content using read_file when needed.
        
        Returns:
            XML-formatted skills summary.
        """
        all_skills = self.list_skills(filter_unavailable=False)
        if not all_skills:
            return ""
        
        def escape_xml(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        lines = ["<skills>"]
        for s in all_skills:
            name = escape_xml(s["name"])
            path = s["path"]
            desc = escape_xml(self._get_skill_description(s["name"]))
            skill_meta = self._get_skill_meta(s["name"])
            available = self._check_requirements(skill_meta)
            
            lines.append(f"  <skill available=\"{str(available).lower()}\">")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{desc}</description>")
            lines.append(f"    <location>{path}</location>")
            
            # Show missing requirements for unavailable skills
            if not available:
                missing = self._get_missing_requirements(skill_meta)
                if missing:
                    lines.append(f"    <requires>{escape_xml(missing)}</requires>")
            
            lines.append(f"  </skill>")
        lines.append("</skills>")
        
        return "\n".join(lines)
    
    # 作用：获取技能缺失需求的描述信息
    # 设计目的：检查CLI工具和环境变量，生成用户友好提示
    # 好处：明确的错误提示，帮助用户安装依赖
    def _get_missing_requirements(self, skill_meta: dict) -> str:
        """Get a description of missing requirements."""
        missing = []
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                missing.append(f"CLI: {b}")
        for env in requires.get("env", []):
            if not os.environ.get(env):
                missing.append(f"ENV: {env}")
        return ", ".join(missing)
    
    # 作用：从技能frontmatter中提取描述信息
    # 设计目的：优先使用元数据描述，回退到技能名称
    # 好处：提供有意义的技能描述，便于用户选择
    def _get_skill_description(self, name: str) -> str:
        """Get the description of a skill from its frontmatter."""
        meta = self.get_skill_metadata(name)
        if meta and meta.get("description"):
            return meta["description"]
        return name  # Fallback to skill name
    
    # 作用：移除Markdown内容中的YAML frontmatter
    # 设计目的：正则匹配YAML块，保留核心技能内容
    # 好处：清理技能内容，避免frontmatter干扰LLM
    def _strip_frontmatter(self, content: str) -> str:
        """Remove YAML frontmatter from markdown content."""
        if content.startswith("---"):
            match = re.match(r"^---\n.*?\n---\n", content, re.DOTALL)
            if match:
                return content[match.end():].strip()
        return content
    
    # 作用：解析frontmatter中的nanobot元数据JSON
    # 设计目的：JSON嵌套在YAML中，提取技能配置信息
    # 好处：结构化技能配置，支持需求检查和特殊标记
    def _parse_nanobot_metadata(self, raw: str) -> dict:
        """Parse nanobot metadata JSON from frontmatter."""
        try:
            data = json.loads(raw)
            return data.get("nanobot", {}) if isinstance(data, dict) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    
    # 作用：检查技能需求是否满足（CLI工具、环境变量）
    # 设计目的：遍历需求列表，验证系统环境
    # 好处：自动技能可用性验证，防止运行环境缺失
    def _check_requirements(self, skill_meta: dict) -> bool:
        """Check if skill requirements are met (bins, env vars)."""
        requires = skill_meta.get("requires", {})
        for b in requires.get("bins", []):
            if not shutil.which(b):
                return False
        for env in requires.get("env", []):
            if not os.environ.get(env):
                return False
        return True
    
    # 作用：获取技能的nanobot元数据（缓存于frontmatter）
    # 设计目的：组合元数据获取和解析，提供统一接口
    # 好处：简化元数据访问，支持缓存优化
    def _get_skill_meta(self, name: str) -> dict:
        """Get nanobot metadata for a skill (cached in frontmatter)."""
        meta = self.get_skill_metadata(name) or {}
        return self._parse_nanobot_metadata(meta.get("metadata", ""))
    
    # 作用：获取标记为always=true且满足需求的技能列表
    # 设计目的：自动加载关键技能，无需显式请求
    # 好处：确保核心技能始终可用，简化用户交互
    def get_always_skills(self) -> list[str]:
        """Get skills marked as always=true that meet requirements."""
        result = []
        for s in self.list_skills(filter_unavailable=True):
            meta = self.get_skill_metadata(s["name"]) or {}
            skill_meta = self._parse_nanobot_metadata(meta.get("metadata", ""))
            if skill_meta.get("always") or meta.get("always"):
                result.append(s["name"])
        return result
    
    # 作用：从技能frontmatter中提取元数据
    # 设计目的：简单YAML解析，提取键值对元数据
    # 好处：技能配置与内容分离，支持丰富元信息
    def get_skill_metadata(self, name: str) -> dict | None:
        """
        Get metadata from a skill's frontmatter.
        
        Args:
            name: Skill name.
        
        Returns:
            Metadata dict or None.
        """
        content = self.load_skill(name)
        if not content:
            return None
        
        if content.startswith("---"):
            match = re.match(r"^---\n(.*?)\n---", content, re.DOTALL)
            if match:
                # Simple YAML parsing
                metadata = {}
                for line in match.group(1).split("\n"):
                    if ":" in line:
                        key, value = line.split(":", 1)
                        metadata[key.strip()] = value.strip().strip('"\'')
                return metadata
        
        return None


# ============================================
# 示例说明：SkillsLoader 使用示例
# ============================================
#
# 1. 基本使用：
# ```python
# from pathlib import Path
# from nanobot.agent.skills import SkillsLoader
#
# workspace = Path("/path/to/workspace")
# loader = SkillsLoader(workspace)
#
# # 列出所有可用技能
# skills = loader.list_skills()
# for skill in skills:
#     print(f"{skill['name']} ({skill['source']}): {skill['path']}")
#
# # 加载特定技能
# content = loader.load_skill("git-expert")
# if content:
#     print(f"技能内容长度: {len(content)}")
# ```
#
# 2. 为智能体上下文加载技能：
# ```python
# # 加载多个技能并格式化
# skill_names = ["git-expert", "docker-basics", "python-debugging"]
# context_content = loader.load_skills_for_context(skill_names)
# print(f"上下文技能内容:\n{context_content[:500]}...")
# ```
#
# 3. 获取技能摘要（用于渐进式加载）：
# ```python
# summary = loader.build_skills_summary()
# print(f"技能XML摘要:\n{summary}")
# ```
#
# 4. 检查技能可用性：
# ```python
# # 获取始终可用的技能
# always_skills = loader.get_always_skills()
# print(f"始终可用的技能: {always_skills}")
#
# # 获取技能元数据
# meta = loader.get_skill_metadata("git-expert")
# print(f"技能元数据: {meta}")
# ```
#
# 5. 技能文件结构示例：
# ```
# skills/
#   git-expert/
#     SKILL.md
#   docker-basics/
#     SKILL.md
#   python-debugging/
#     SKILL.md
# ```
#
# 6. SKILL.md 文件格式示例：
# ```markdown
# ---
# description: "Git版本控制专家技能"
# author: "团队"
# metadata: |
#   {
#     "nanobot": {
#       "requires": {
#         "bins": ["git"],
#         "env": ["GITHUB_TOKEN"]
#       },
#       "always": true
#     }
#   }
# ---
#
# # Git专家技能
#
# 本技能教你如何高效使用Git进行版本控制...
# ```
