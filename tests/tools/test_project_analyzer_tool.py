"""Tests for ProjectAnalyzerTool."""

import pytest

from nanobot.agent.tools.project_analyzer import (
    ProjectAnalyzerTool,
    _is_sensitive_path,
    _parse_pyproject_toml,
    _safe_read_file,
    _get_user_home,
)


class TestProjectAnalyzerTool:

    @pytest.fixture()
    def tool(self):
        return ProjectAnalyzerTool()

    @pytest.fixture()
    def sample_project(self, tmp_path):
        """Create a sample Python project structure."""
        project = tmp_path / "myproject"
        project.mkdir()
        
        readme = project / "README.md"
        readme.write_text("""# MyProject

这是一个示例 Python 项目。

## 功能特性

- 功能 A
- 功能 B
- 功能 C

## 安装

```bash
pip install -e .
```

## 使用

```python
import myproject
myproject.run()
```
""", encoding="utf-8")
        
        pyproject = project / "pyproject.toml"
        pyproject.write_text("""[project]
name = "myproject"
version = "1.0.0"
description = "A sample Python project for testing"
requires-python = ">=3.10"
dependencies = [
    "requests>=2.28.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "ruff>=0.1.0",
]

[project.scripts]
myproject = "myproject.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
""", encoding="utf-8")
        
        requirements = project / "requirements.txt"
        requirements.write_text("""# Main dependencies
requests>=2.28.0
pydantic>=2.0.0

# Dev dependencies
pytest>=7.0.0
ruff>=0.1.0
""", encoding="utf-8")
        
        src = project / "myproject"
        src.mkdir()
        
        init_file = src / "__init__.py"
        init_file.write_text('''"""MyProject package."""

__version__ = "1.0.0"


def run():
    """Run the main application."""
    print("Hello from MyProject!")
''', encoding="utf-8")
        
        cli = src / "cli.py"
        cli.write_text('''"""Command-line interface."""

import argparse


def main():
    """Entry point for the CLI."""
    parser = argparse.ArgumentParser(description="MyProject CLI")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    
    if args.verbose:
        print("Running in verbose mode")
    print("MyProject CLI executed successfully")


if __name__ == "__main__":
    main()
''', encoding="utf-8")
        
        main_py = project / "main.py"
        main_py.write_text('''"""Main entry point."""

from myproject import run


if __name__ == "__main__":
    run()
''', encoding="utf-8")
        
        return project

    @pytest.mark.asyncio
    async def test_basic_project_analysis(self, tool, sample_project):
        """Test basic project analysis produces expected sections."""
        result = await tool.execute(path=str(sample_project))
        
        assert "项目分析报告" in result
        assert "项目简介" in result
        assert "目录结构" in result
        assert "运行方式" in result
        assert "核心模块" in result
        assert "依赖分析" in result
        assert "可优化点" in result
        assert "潜在风险" in result
        
        assert "myproject" in result
        assert "1.0.0" in result
        assert "sample Python project" in result
        
        assert "requests" in result
        assert "pydantic" in result
        
        assert "main.py" in result.lower() or "cli.py" in result.lower()

    @pytest.mark.asyncio
    async def test_missing_path_parameter(self, tool):
        """Test error when path is not provided."""
        result = await tool.execute()
        assert "Error" in result
        assert "path" in result.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_path(self, tool, tmp_path):
        """Test error when path does not exist."""
        nonexistent = tmp_path / "nonexistent"
        result = await tool.execute(path=str(nonexistent))
        assert "Error" in result
        assert "not exist" in result.lower() or "不存在" in result

    @pytest.mark.asyncio
    async def test_file_instead_of_directory(self, tool, tmp_path):
        """Test error when path is a file, not a directory."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("not a directory")
        result = await tool.execute(path=str(test_file))
        assert "Error" in result
        assert "not a directory" in result.lower() or "不是目录" in result

    @pytest.mark.asyncio
    async def test_project_with_only_readme(self, tool, tmp_path):
        """Test analysis of project with only README."""
        project = tmp_path / "simple_project"
        project.mkdir()
        readme = project / "README.md"
        readme.write_text("# Simple Project\n\nA very simple project.", encoding="utf-8")
        
        result = await tool.execute(path=str(project))
        
        assert "项目分析报告" in result
        assert "Simple Project" in result

    @pytest.mark.asyncio
    async def test_empty_directory(self, tool, tmp_path):
        """Test analysis of empty directory."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        
        result = await tool.execute(path=str(empty_dir))
        
        assert "项目分析报告" in result
        assert "empty" in result.lower() or "未检测" in result


class TestPathSecurity:

    def test_is_sensitive_path_blocks_root(self, tmp_path):
        """Test that root paths are blocked."""
        import os
        from pathlib import Path
        
        if os.name == 'nt':
            c_drive = Path("C:\\")
            assert _is_sensitive_path(c_drive)
        else:
            root = Path("/")
            assert _is_sensitive_path(root)

    def test_is_sensitive_path_blocks_etc(self, tmp_path):
        """Test that /etc is blocked on Unix."""
        import os
        from pathlib import Path
        
        if os.name != 'nt':
            etc_path = Path("/etc")
            assert _is_sensitive_path(etc_path)

    def test_is_sensitive_path_blocks_windows(self, tmp_path):
        """Test that Windows system directories are blocked."""
        import os
        from pathlib import Path
        
        if os.name == 'nt':
            windows_path = Path("C:\\Windows")
            assert _is_sensitive_path(windows_path)
            
            program_files = Path("C:\\Program Files")
            assert _is_sensitive_path(program_files)

    def test_normal_project_path_is_not_sensitive(self, tmp_path):
        """Test that normal project paths are allowed."""
        project = tmp_path / "myproject"
        project.mkdir()
        assert not _is_sensitive_path(project)


class TestParsePyprojectToml:

    def test_parse_basic_pyproject(self):
        """Test parsing a basic pyproject.toml."""
        content = """[project]
name = "testpkg"
version = "0.1.0"
description = "Test package"
dependencies = ["requests", "pydantic"]

[project.scripts]
testcli = "testpkg.cli:main"
"""
        result = _parse_pyproject_toml(content)
        
        assert result["name"] == "testpkg"
        assert result["version"] == "0.1.0"
        assert result["description"] == "Test package"
        assert "requests" in result["dependencies"]
        assert "pydantic" in result["dependencies"]
        assert "testcli" in result["entry_points"]

    def test_parse_empty_pyproject(self):
        """Test parsing an empty pyproject.toml."""
        content = ""
        result = _parse_pyproject_toml(content)
        
        assert result["name"] is None
        assert result["version"] is None
        assert result["dependencies"] == []

    def test_parse_poetry_config(self):
        """Test parsing a poetry-based pyproject.toml."""
        content = """[tool.poetry]
name = "poetry-pkg"
version = "2.0.0"
description = "Poetry package"

[tool.poetry.dependencies]
python = "^3.10"
requests = "^2.28.0"
pydantic = "^2.0.0"

[tool.poetry.group.dev.dependencies]
pytest = "^7.0.0"
"""
        result = _parse_pyproject_toml(content)
        
        assert result["name"] == "poetry-pkg"
        assert result["version"] == "2.0.0"
        assert any("requests" in d for d in result["dependencies"])
        assert any("pydantic" in d for d in result["dependencies"])


class TestSafeReadFile:

    def test_read_existing_file(self, tmp_path):
        """Test reading an existing file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!", encoding="utf-8")
        
        content = _safe_read_file(test_file)
        assert content == "Hello, World!"

    def test_read_nonexistent_file(self, tmp_path):
        """Test reading a non-existent file returns empty string."""
        nonexistent = tmp_path / "nonexistent.txt"
        content = _safe_read_file(nonexistent)
        assert content == ""

    def test_read_directory_returns_empty(self, tmp_path):
        """Test that reading a directory returns empty string."""
        content = _safe_read_file(tmp_path)
        assert content == ""


class TestGetUserHome:

    def test_get_user_home_returns_valid_path(self):
        """Test that _get_user_home returns a valid path."""
        home = _get_user_home()
        assert home is not None
        assert isinstance(home, type(__import__('pathlib').Path()))
