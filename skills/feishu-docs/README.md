# feishu-docs

飞书云文档 skill for nanobot - 读取、搜索飞书云文档内容。

## 功能

- 📄 列出云文档列表
- 📖 读取文档内容
- 🔍 搜索云文档

## 快速开始

### 1. 安装依赖

```bash
pip install requests
```

### 2. 配置环境变量

```bash
export FEISHU_APP_ID="你的App ID"
export FEISHU_APP_SECRET="你的App Secret"
```

### 3. 运行测试

```bash
# 单元测试
python3 -m unittest discover -v tests/

# 集成测试（需要配置环境变量）
FEISHU_APP_ID=xxx FEISHU_APP_SECRET=xxx python3 -m unittest tests.test_integration -v
```

## 项目结构

```
feishu-docs/
├── SKILL.md              # Skill 文档
├── src/
│   ├── __init__.py
│   ├── client.py         # API 客户端
│   └── tools.py          # 工具函数
└── tests/
    ├── test_client.py    # 客户端单元测试
    ├── test_tools.py    # 工具单元测试
    └── test_integration.py # 集成测试
```

## 开发

### 运行测试

```bash
cd feishu-docs
python3 -m unittest discover -v tests/
```

### 代码规范

- 使用 Python 3.8+
- 遵循 PEP 8
- 所有新增代码需要测试覆盖

## License

MIT
