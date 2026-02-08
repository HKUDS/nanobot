# Nanobot 单元测试与调试指南

本文档以 `TestIsOllama` 为例，详细介绍如何编写、运行和调试单元测试。

---

## 📋 目录

1. [测试框架概述](#测试框架概述)
2. [测试文件结构](#测试文件结构)
3. [编写测试用例](#编写测试用例)
4. [运行测试](#运行测试)
5. [调试技巧](#调试技巧)
6. [常见问题](#常见问题)
7. [最佳实践](#最佳实践)

---

## 测试框架概述

### 技术栈

| 组件 | 用途 | 版本 |
|-----|------|------|
| **pytest** | 测试框架核心 | >=7.0.0 |
| **pytest-asyncio** | 异步测试支持 | >=0.21.0 |

### 配置位置

测试配置在 `pyproject.toml` 中：

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 测试文件结构

### 目录布局

```
nanobot/
├── tests/                          # 测试目录
│   ├── __init__.py                 # 空文件，使 tests 成为包
│   ├── test_litellm_provider.py    # LiteLLMProvider 测试
│   ├── test_tool_validation.py     # 工具验证测试
│   └── ...                         # 其他测试文件
├── nanobot/                        # 源代码
│   └── providers/
│       └── litellm_provider.py     # 被测代码
└── pyproject.toml                  # 测试配置
```

### 命名规范

| 项目 | 命名规则 | 示例 |
|-----|---------|------|
| 测试文件 | `test_*.py` | `test_litellm_provider.py` |
| 测试类 | `Test*` | `TestIsOllama` |
| 测试方法 | `test_*` | `test_is_ollama_true_with_ollama_in_model` |

---

## 编写测试用例

### 完整示例：TestIsOllama

```python
"""Tests for LiteLLMProvider."""

# 模块作用：LiteLLMProvider 的单元测试，验证 Ollama 检测逻辑
# 设计目的：确保 is_ollama 属性在各种场景下正确识别本地 Ollama 部署
# 好处：防止回归错误，保障本地 LLM 集成的可靠性
import pytest
from nanobot.providers.litellm_provider import LiteLLMProvider


# 作用：测试 is_ollama 属性的各种场景检测
# 设计目的：覆盖正常情况和边界情况，确保检测逻辑健壮
# 好处：全面验证 Ollama 检测，防止误判或漏判
class TestIsOllama:
    """Test is_ollama property detection."""

    # 作用：测试模型名包含 'ollama' 时正确识别为 Ollama
    # 设计目的：验证最基本的正向检测场景
    # 好处：确保标准 Ollama 模型格式被正确识别
    def test_is_ollama_true_with_ollama_in_model(self):
        """Test is_ollama is True when model contains 'ollama'."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://localhost:11434",
            default_model="ollama/llama3.2"
        )
        assert provider.is_ollama is True
 
    
    # 作用：测试使用 127.0.0.1 地址的典型 Ollama 设置
    # 设计目的：验证本地地址配置的正确识别
    # 好处：覆盖常见的本地部署场景，包括带 /v1 路径的端点
    def test_is_ollama_with_localhost_api_base(self):
        """Test is_ollama with typical Ollama localhost setup."""
        provider = LiteLLMProvider(
            api_key="dummy",
            api_base="http://127.0.0.1:11434/v1",
            default_model="ollama/mistral"
        )
        assert provider.is_ollama is True

    # 作用：批量测试多种 Ollama 模型名称的识别
    # 设计目的：参数化测试，覆盖多种 Ollama 模型格式
    # 好处：一次性验证多种模型，提高测试效率和覆盖率
    def test_is_ollama_with_different_ollama_models(self):
        """Test is_ollama with various Ollama model names."""
        # 测试用例：(模型名称, 预期结果)
        test_cases = [
            ("ollama/llama3.2", True),
            ("ollama/mistral", True),
            ("ollama/codellama", True),
            ("ollama/gemma:2b", True),
            ("ollama/phi3", True),
            ("claude-3-opus", False),
            ("gpt-4", False),
            ("gemini-pro", False),
        ]
        
        for model, expected in test_cases:
            provider = LiteLLMProvider(
                api_key="dummy",
                api_base="http://localhost:11434",
                default_model=model
            )
            assert provider.is_ollama == expected, f"Failed for model: {model}"

 
```

### 测试结构解析

#### 1. 三层注释体系

```python
# 第一层：模块/类级别 - 说明整体功能
# 模块作用：...
# 设计目的：...
# 好处：...

class TestXxx:
    # 第二层：类级别 - 说明测试范围
    # 作用：...
    # 设计目的：...
    # 好处：...
    
    def test_xxx(self):
        # 第三层：方法级别 - 说明具体测试点
        # 作用：...
        # 设计目的：...
        # 好处：...
```

#### 2. 测试方法结构

```python
def test_xxx(self):
    """简短的测试描述（显示在测试报告中）。"""
    # 1. 准备（Arrange）
    provider = LiteLLMProvider(...)
    
    # 2. 执行（Act）
    result = provider.is_ollama
    
    # 3. 断言（Assert）
    assert result is True
```

---

## 运行测试

### 环境准备

```bash
# 1. 进入项目目录
cd e:/myAiProject/nanobot

# 2. 安装依赖（包含测试依赖）
pip install -e ".[dev]"

# 3. 验证安装
python -m pytest --version
```

### 运行命令详解

#### 1. 运行整个测试类

```bash
# 语法：pytest 文件路径::类名
python -m pytest tests/test_litellm_provider.py::TestIsOllama -v
```

**输出示例：**
```
tests/test_litellm_provider.py::TestIsOllama::test_is_ollama_true_with_ollama_in_model PASSED [ 11%]
tests/test_litellm_provider.py::TestIsOllama::test_is_ollama_true_with_uppercase PASSED [ 22%]
...
============================== 9 passed in 0.15s ===============================
```

#### 2. 运行单个测试方法

```bash
# 语法：pytest 文件路径::类名::方法名
python -m pytest tests/test_litellm_provider.py::TestIsOllama::test_is_ollama_true_with_ollama_in_model -v
```

#### 3. 运行整个测试文件

```bash
python -m pytest tests/test_litellm_provider.py -v
```

#### 4. 运行所有测试

```bash
python -m pytest -v
# 或
python -m pytest tests/ -v
```

### 常用参数

| 参数 | 作用 | 示例 |
|-----|------|------|
| `-v` | 详细输出 | `pytest -v` |
| `-s` | 显示 print 输出 | `pytest -s` |
| `-x` | 首次失败即停止 | `pytest -x` |
| `-k` | 按名称过滤 | `pytest -k "ollama"` |
| `--tb=short` | 简短错误信息 | `pytest --tb=short` |
| `--tb=long` | 完整错误信息 | `pytest --tb=long` |
| `-q` | 安静模式 | `pytest -q` |
| `--lf` | 只运行上次失败的 | `pytest --lf` |
| `--ff` | 先运行上次失败的 | `pytest --ff` |

---

## 调试技巧

### 方法一：使用 print 输出

```python
def test_is_ollama_debug(self):
    """Debug version with print statements."""
    provider = LiteLLMProvider(
        api_key="dummy",
        api_base="http://localhost:11434",
        default_model="ollama/llama3.2"
    )
    
    # 添加调试输出
    print(f"\napi_base: {provider.api_base}")
    print(f"default_model: {provider.default_model}")
    print(f"is_ollama: {provider.is_ollama}")
    
    assert provider.is_ollama is True
```

**运行（需要 `-s` 参数）：**
```bash
python -m pytest tests/test_litellm_provider.py::TestIsOllama::test_is_ollama_debug -v -s
```

### 方法二：使用 pytest 的 pdb 调试

```bash
# 失败时自动进入 pdb
python -m pytest tests/test_litellm_provider.py::TestIsOllama -v --pdb

# 在代码中设置断点
import pytest

def test_xxx(self):
    ...
    pytest.set_trace()  # 断点
    ...
```

### 方法三：VS Code 调试配置

创建 `.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Debug Tests",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": [
        "tests/test_litellm_provider.py::TestIsOllama",
        "-v"
      ],
      "console": "integratedTerminal",
      "justMyCode": false
    },
    {
      "name": "Python: Debug Current Test",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": [
        "${relativeFile}::${selectedText}",
        "-v"
      ],
      "console": "integratedTerminal"
    }
  ]
}
```

**使用步骤：**
1. 在测试代码中设置断点（点击行号左侧）
2. 选择调试配置 "Python: Debug Tests"
3. 按 F5 启动调试
4. 使用 F10（单步跳过）、F11（单步进入）

### 方法四：直接运行 Python 代码

创建临时调试脚本 `debug_test.py`：

```python
"""临时调试脚本。"""
from nanobot.providers.litellm_provider import LiteLLMProvider

# 测试场景 1：正常情况
provider1 = LiteLLMProvider(
    api_key="dummy",
    api_base="http://localhost:11434",
    default_model="ollama/llama3.2"
)
print(f"Test 1 - Expected True: {provider1.is_ollama}")

# 测试场景 2：无 api_base
provider2 = LiteLLMProvider(
    api_key="dummy",
    api_base=None,
    default_model="ollama/llama3.2"
)
print(f"Test 2 - Expected False: {provider2.is_ollama}")

# 测试场景 3：GPT 模型
provider3 = LiteLLMProvider(
    api_key="dummy",
    api_base="http://localhost:11434",
    default_model="gpt-4"
)
print(f"Test 3 - Expected False: {provider3.is_ollama}")
```

运行：
```bash
python debug_test.py
```

---

## 常见问题

### 问题 1：ModuleNotFoundError

**现象：**
```
ModuleNotFoundError: No module named 'nanobot'
```

**解决：**
```bash
# 确保在项目根目录，并安装项目
pip install -e .

# 或设置 PYTHONPATH
export PYTHONPATH=$PYTHONPATH:e:/myAiProject/nanobot
```

### 问题 2：ImportError: No module named 'litellm'

**现象：**
```
ModuleNotFoundError: No module named 'litellm'
```

**解决：**
```bash
# 安装项目及其依赖
pip install -e ".[dev]"

# 或单独安装 litellm
pip install litellm
```

### 问题 3：测试未被收集

**现象：**
```
collected 0 items
```

**原因与解决：**
1. **文件名不规范** → 必须以 `test_` 开头
2. **类名不规范** → 必须以 `Test` 开头
3. **方法名不规范** → 必须以 `test_` 开头
4. **缺少 `__init__.py`** → 在 `tests/` 目录添加空文件

### 问题 4：断言失败但不知道原因

**解决：**
```python
# 添加详细错误信息
assert provider.is_ollama == expected, (
    f"is_ollama should be {expected} but got {provider.is_ollama}. "
    f"api_base={provider.api_base}, model={provider.default_model}"
)
```

---

## 最佳实践

### 1. 测试命名规范

| 场景 | 好的命名 | 不好的命名 |
|-----|---------|-----------|
| 正向测试 | `test_is_ollama_true_with_ollama_in_model` | `test1` |
| 负向测试 | `test_is_ollama_false_without_api_base` | `test_fail` |
| 边界测试 | `test_is_ollama_false_with_empty_api_base` | `test_edge` |

### 2. 一个测试只测一个概念

```python
# ✅ 好的做法：每个测试一个断言
def test_is_ollama_true_with_ollama_in_model(self):
    provider = create_provider("ollama/llama3.2")
    assert provider.is_ollama is True

def test_is_ollama_false_with_gpt_model(self):
    provider = create_provider("gpt-4")
    assert provider.is_ollama is False

# ❌ 不好的做法：一个测试多个不相关断言
def test_is_ollama(self):  # 不要这样
    provider1 = create_provider("ollama/llama3.2")
    assert provider1.is_ollama is True
    
    provider2 = create_provider("gpt-4")
    assert provider2.is_ollama is False
```

### 3. 使用参数化测试批量验证

```python
import pytest

@pytest.mark.parametrize("model,expected", [
    ("ollama/llama3.2", True),
    ("ollama/mistral", True),
    ("gpt-4", False),
])
def test_is_ollama_parametrized(self, model, expected):
    """使用 pytest 的参数化功能。"""
    provider = LiteLLMProvider(
        api_key="dummy",
        api_base="http://localhost:11434",
        default_model=model
    )
    assert provider.is_ollama == expected
```

### 4. 测试覆盖率检查

```bash
# 安装 coverage 工具
pip install pytest-cov

# 运行测试并生成覆盖率报告
python -m pytest tests/test_litellm_provider.py --cov=nanobot.providers.litellm_provider --cov-report=html

# 查看报告
# 打开 htmlcov/index.html
```

### 5. 持续集成配置

GitHub Actions 示例（`.github/workflows/test.yml`）：

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          pip install -e ".[dev]"
      
      - name: Run tests
        run: |
          pytest tests/ -v --cov=nanobot --cov-report=xml
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

---

## 总结

| 任务 | 命令 |
|-----|------|
| 安装测试依赖 | `pip install -e ".[dev]"` |
| 运行所有测试 | `python -m pytest -v` |
| 运行单个测试类 | `python -m pytest tests/test_litellm_provider.py::TestIsOllama -v` |
| 运行单个测试方法 | `python -m pytest tests/...::TestIsOllama::test_is_ollama_true... -v` |
| 调试测试 | VS Code + F5 或 `pytest --pdb` |
| 检查覆盖率 | `pytest --cov=nanobot --cov-report=html` |

---

**参考文件：**
- 测试文件：`tests/test_litellm_provider.py`
- 被测代码：`nanobot/providers/litellm_provider.py`
- 配置文件：`pyproject.toml`
