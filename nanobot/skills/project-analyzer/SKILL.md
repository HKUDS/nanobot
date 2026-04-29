---
name: project-analyzer
description: Analyze local Python projects to understand structure, dependencies, and entry points. Use when the user wants to analyze a local Python project directory for overview, structure, dependencies, or potential issues. Requires an explicit, existing directory path.
---

# Project Analyzer Skill

This skill guides the agent in using the `project_analyzer` tool to analyze local Python project directories.

## When to Use

Use this skill when:
- The user asks to "analyze this project" or "understand this codebase"
- The user wants an overview of a Python project's structure
- The user needs to know project dependencies, entry points, or run commands
- The user asks about potential issues or optimization points in a project
- The user provides an explicit directory path for analysis

## Important Requirements

**MUST require an explicit directory path** from the user before using the `project_analyzer` tool.

Never:
- Assume a default path
- Use relative paths like `.` without explicit confirmation
- Use the current workspace directory unless explicitly requested

When the user mentions analyzing a project but doesn't provide a clear path:
1. Ask for the explicit directory path
2. Confirm the path is correct before proceeding

## Tool Usage

Use the `project_analyzer` tool with the explicit path parameter:

```python
project_analyzer(path="/absolute/path/to/project")
```

## What the Tool Provides

The `project_analyzer` tool returns a Markdown report containing:

1. **Project Overview** - Project name, version, description, author, file count
2. **Directory Structure** - Directory tree structure
3. **Dependencies** - Dependencies from pyproject.toml or requirements.txt
4. **How to Run** - Entry points, scripts, or suggested run commands
5. **Core Modules** - Key Python files with preview content
6. **Suggested Improvements** - Suggestions for improvement
7. **Potential Risks** - Security or compatibility concerns

## Security Restrictions

The tool will reject paths that are:
- System root directories (e.g., `C:\`, `/`)
- User home root directories
- System directories (e.g., `C:\Windows`, `/usr`)

The tool will NOT follow:
- Symlinks that point outside the project directory
- Symlinks within the project directory

Do not attempt to bypass these restrictions.
