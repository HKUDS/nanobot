# AGENTS.md

## Project Overview

**Purpose**: nanobot is a lightweight personal AI assistant framework built in Python, supporting multiple AI providers (OpenAI, Anthropic, Azure, Ollama, etc.) and communication channels (CLI, Web UI, Feishu, etc.).

## Development Environment & Dependencies

**Package Manager**: pip + pyproject.toml

**Installation**:
```bash
pip install -e .[dev]
```

## Testing & Validation

**Test Framework**: pytest

**Run Tests**:
```bash
# Run all tests
pytest
# Run all tests with coverage
pytest --cov=nanobot
```

**Run Specific Tests**:
```bash
# Run tests in a specific file
pytest tests/test_filename.py
# Run specific test class or function
pytest tests/test_filename.py::TestClass::test_function
```


## Code Standards & Constraints

**Naming Conventions**:
- Variables, Functions: snake_case
- Class names: PascalCase
- Constants: UPPER_SNAKE_CASE

**Project Structure**:
- `nanobot/`: Core source code
- `tests/`: Test files
- `pyproject.toml`: Dependency management
- `README.md`: Project documentation

**Prohibited**:
- Hardcoding sensitive information
- Using deprecated Python syntax
- Must maintain Python 3.11+ compatibility

**Compatibility**: Code must be compatible with Python 3.11+

## Security & Workflow

**Sensitive Information**: Strictly prohibit hardcoding API keys, passwords, or other sensitive data. Must use environment variables or config files.

**Commit Message Format**:
```
type: description
```

Or with scope:
```
type(scope): description
```

**Examples**:
- `feat: add WeChat channel support`
- `fix(gateway): resolve connection timeout issue`
- `docs: update AGENTS.md for AI coding assistants`

**Types**:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation update
- `style`: Code formatting
- `refactor`: Code refactoring
- `test`: Test-related changes
- `chore`: Build or tooling changes

**Actions Requiring Confirmation**:
- Modifying critical configuration parameters
- Deleting or renaming core modules
- Modifying AI provider authentication logic
- Changing project dependencies
