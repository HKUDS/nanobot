# Nanobot Web 设置功能 & UI 现代化计划

> 日期: 2025-03-16
> 状态: 设计阶段
> 原则: 保持现有 UI 结构，渐进式改进

---

## 一、项目目标

### 1.1 核心功能
- [ ] 设置面板（模版、定时任务、MCP、Skills）
- [ ] 预设药理基因组学分析模版
- [ ] 配置热加载（无需重启）

### 1.2 UI 现代化
- [ ] 代码语法高亮
- [ ] 工具调用可视化
- [ ] 流式输出优化
- [ ] 交互动画
- [ ] 主题系统（亮/暗切换）

---

## 二、架构设计

### 2.1 目录结构（新增/修改）

```
nanobot/
├── web/
│   ├── __init__.py
│   ├── server.py                    # [修改] 添加新 API 路由
│   ├── api/                         # [新增] API 模块
│   │   ├── __init__.py
│   │   ├── settings.py              # 设置 CRUD
│   │   ├── templates.py             # 模版 CRUD
│   │   └── cron_api.py              # 定时任务 API
│   ├── schemas/                     # [新增] 数据模型
│   │   ├── __init__.py
│   │   ├── template.py              # 模版数据结构
│   │   └── settings.py              # 设置请求/响应
│   └── static/
│       ├── index.html               # [修改] 添加设置按钮、模态框
│       ├── css/
│       │   └── settings.css         # [新增] 设置面板样式
│       ├── js/
│       │   ├── settings.js          # [新增] 设置面板逻辑
│       │   └── ui-enhance.js        # [新增] UI 现代化组件
│       └── libs/                    # [新增] 第三方库
│           ├── prism.min.css        # 代码高亮
│           ├── prism.min.js
│           └── lucide.min.js        # 图标库
│
├── templates/
│   └── web/                         # [新增] Web 模版存储
│       └── pharmacogenomics.json    # 预设药理基因组学模版
│
└── config/
    └── schema.py                    # [可能修改] 添加模版配置
```

### 2.2 API 端点设计

| 端点 | 方法 | 功能 |
|------|------|------|
| `/api/settings` | GET | 获取所有设置 |
| `/api/settings` | PATCH | 更新设置 |
| `/api/templates` | GET | 列出所有模版 |
| `/api/templates` | POST | 创建模版 |
| `/api/templates/{id}` | GET | 获取模版详情 |
| `/api/templates/{id}` | DELETE | 删除模版 |
| `/api/templates/{id}/apply` | POST | 应用模版到当前会话 |
| `/api/cron` | GET | 列出定时任务 |
| `/api/cron` | POST | 创建定时任务 |
| `/api/cron/{id}` | DELETE | 删除定时任务 |
| `/api/cron/{id}/run` | POST | 立即运行任务 |
| `/api/mcp` | GET | 列出 MCP 服务器 |
| `/api/mcp` | POST | 添加 MCP 服务器 |
| `/api/mcp/{name}` | DELETE | 删除 MCP 服务器 |

---

## 三、数据模型

### 3.1 模版数据结构

```python
# nanobot/web/schemas/template.py
from pydantic import BaseModel
from typing import Optional

class TemplateConfig(BaseModel):
    """模版配置"""
    id: str                           # 唯一标识
    name: str                         # 显示名称
    description: str                  # 描述
    system_prompt: str                # 系统提示词
    user_identity: str                # 用户身份定义
    agent_identity: str               # Agent 身份定义
    required_mcps: list[str] = []     # 需要的 MCP 服务器
    required_tools: list[str] = []    # 需要的工具
    example_query: str = ""           # 示例查询
    icon: str = "📋"                  # 图标
```

### 3.2 预设模版：药理基因组学

```json
{
  "id": "pharmacogenomics",
  "name": "药理基因组学分析",
  "description": "输入基因，查询药物敏感关系，整合 ClinPGx/PharmGKB/CPIC/FDA 数据，生成专业报告",
  "system_prompt": "你是一个药物基因组学专家助手。\n\n当用户提供基因名称时，你需要：\n1. 使用 Exa MCP 搜索该基因与药物敏感性的关系\n2. 查询 ClinPGx、PharmGKB、CPIC、FDA 等权威数据库\n3. 整合搜索结果，生成结构化报告\n\n报告应包括：\n- 基因基本信息\n- 相关药物列表\n- 药物敏感性/耐药性\n- 临床意义\n- 参考文献",
  "user_identity": "用户是药理基因组学研究者，具备分子生物学和药学背景。",
  "agent_identity": "你是药物基因组学分析助手，擅长整合多源数据，生成专业报告。",
  "required_mcps": ["exa"],
  "required_tools": ["web_search", "exec"],
  "example_query": "CYP2C19 基因与氯吡格雷的药物敏感关系",
  "icon": "💊"
}
```

---

## 四、UI 设计

### 4.1 设置面板布局

```
┌───────────────────────────────────────────────────────────────────┐
│ 设置                                              ✕               │
├───────────────┬───────────────────────────────────────────────────┤
│ 左侧导航       │ 右侧内容区                                        │
│               │                                                   │
│ 📋 模版       │ ┌─────────────────┐  ┌─────────────────┐         │
│ ⏰ 定时任务   │ │ 💊 药物基因组学  │  │ 📋 通用助手     │         │
│ 🔧 MCP 服务器  │ │ 输入基因查询... │  │ 日常对话        │         │
│ ⚡ Skills     │ │      [应用]      │  │     [应用]      │         │
│ 🎨 外观       │ └─────────────────┘  └─────────────────┘         │
│               │                                                   │
│ [+ 新建模版]  │ ┌─────────────────┐  ┌─────────────────┐         │
│               │ │ 💻 代码助手     │  │ 📊 数据分析     │         │
│               │ │ 编程辅助...     │  │ 统计分析...     │         │
│               │ │      [应用]      │  │     [应用]      │         │
│               │ └─────────────────┘  └─────────────────┘         │
└───────────────┴───────────────────────────────────────────────────┘
```

### 4.2 主界面修改点

```html
<!-- Header 添加设置按钮 -->
<header class="px-6 py-3 border-b border-gray-800 flex items-center gap-3">
  <span id="header-session">web:default</span>
  <span class="ml-auto"></span>
  <button id="btn-settings" class="text-gray-400 hover:text-white transition-colors">
    ⚙️ 设置
  </button>
  <span id="status-indicator"></span>
</header>

<!-- 输入框上方添加模版快捷选择 -->
<div id="template-bar" class="px-4 py-2 border-b border-gray-800/50">
  <div class="flex gap-2 overflow-x-auto">
    <button class="template-chip">💊 药物基因组学</button>
    <button class="template-chip">💻 代码助手</button>
    <button class="template-chip">📊 数据分析</button>
  </div>
</div>
```

### 4.3 现代化组件

#### 代码块高亮
```javascript
// 集成 Prism.js
const codeBlock = document.createElement('pre');
codeBlock.innerHTML = `<code class="language-python">${code}</code>`;
Prism.highlightElement(codeBlock);
```

#### 工具调用卡片
```javascript
function appendToolCard(toolName, input, output) {
  return `
    <div class="tool-card bg-gray-800/50 rounded-lg p-3 mb-2 border border-gray-700">
      <div class="flex items-center gap-2 text-sm text-gray-400 mb-2">
        <span class="w-2 h-2 rounded-full ${getStatusColor(output)}"></span>
        <span class="font-mono">${toolName}</span>
      </div>
      <div class="text-xs text-gray-500 font-mono">${escapeHtml(input)}</div>
      ${output ? `<div class="text-xs text-green-400 mt-1">${output}</div>` : ''}
    </div>
  `;
}
```

---

## 五、实现步骤

### Phase 1: 基础设置面板（P0）

- [ ] **Step 1.1**: 创建数据模型 (`schemas/template.py`, `schemas/settings.py`)
- [ ] **Step 1.2**: 实现模版 API (`api/templates.py`)
- [ ] **Step 1.3**: 实现设置 API (`api/settings.py`)
- [ ] **Step 1.4**: 注册路由到 `server.py`
- [ ] **Step 1.5**: 前端设置面板 HTML 结构
- [ ] **Step 1.6**: 前端设置面板 JS 逻辑
- [ ] **Step 1.7**: 模版应用逻辑（注入系统提示词）

### Phase 2: 预设模版（P0）

- [ ] **Step 2.1**: 创建 `templates/web/` 目录
- [ ] **Step 2.2**: 编写 `pharmacogenomics.json`
- [ ] **Step 2.3**: 模版加载逻辑
- [ ] **Step 2.4**: 模版快捷选择 chips

### Phase 3: 定时任务管理（P1）

- [ ] **Step 3.1**: 实现定时任务 API (`api/cron_api.py`)
- [ ] **Step 3.2**: 前端定时任务列表
- [ ] **Step 3.3**: 前端创建/编辑任务表单
- [ ] **Step 3.4**: 任务状态实时更新

### Phase 4: MCP 服务器管理（P1）

- [ ] **Step 4.1**: 实现 MCP API (`api/mcp.py`)
- [ ] **Step 4.2**: 前端 MCP 服务器列表
- [ ] **Step 4.3**: 前端添加 MCP 服务器表单
- [ ] **Step 4.4**: MCP 连接状态显示

### Phase 5: UI 现代化（P2）

- [ ] **Step 5.1**: 集成 Prism.js 代码高亮
- [ ] **Step 5.2**: 工具调用可视化卡片
- [ ] **Step 5.3**: 流式输出打字机效果优化
- [ ] **Step 5.4**: 添加过渡动画
- [ ] **Step 5.5**: 卡片阴影和圆角升级
- [ ] **Step 5.6**: 代码块一键复制

### Phase 6: 主题系统（P2）

- [ ] **Step 6.1**: 定义主题 CSS 变量
- [ ] **Step 6.2**: 亮色主题
- [ ] **Step 6.3**: 主题切换逻辑
- [ ] **Step 6.4**: 持久化主题选择

### Phase 7: Skills 管理（P3）

- [ ] **Step 7.1**: 实现 Skills API
- [ ] **Step 7.2**: 前端 Skills 列表
- [ ] **Step 7.3**: Skills 启用/禁用

---

## 六、技术细节

### 6.1 配置热加载

```python
# 在 AgentLoop 中添加 reload_config 方法
async def reload_config(self):
    """重新加载配置"""
    cfg = _load_runtime_config(self._config_path, self._workspace)
    self.web_search_config = cfg.tools.web.search
    self.mcp_servers = cfg.tools.mcp_servers
    # 需要时重连 MCP
```

### 6.2 模版应用机制

```python
# 在 process_direct 中添加 system_prompt_override 参数
async def process_direct(
    self,
    message: str,
    *,
    system_prompt_override: str | None = None,
    # ...
):
    if system_prompt_override:
        self._system_prompt = system_prompt_override
    # ...
```

### 6.3 SSE 事件扩展

```javascript
// 新增事件类型
{
  type: "tool_start",  // 工具开始执行
  tool: "web_search",
  input: "搜索 CYP2C19"
}
{
  type: "tool_end",    // 工具执行结束
  tool: "web_search",
  output: "找到 5 个结果"
}
```

---

## 七、依赖添加

```toml
# pyproject.toml
[project.optional-dependencies]
web = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
]
```

前端 CDN 依赖：
- Tailwind CSS（已有）
- Marked.js（已有）
- Prism.js（新增）
- Lucide Icons（新增）

---