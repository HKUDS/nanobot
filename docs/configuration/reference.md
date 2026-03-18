# 完整設定參考

本頁記錄 `~/.nanobot/config.json` 中每一個設定選項，包含型別、預設值與說明。

> [!NOTE]
> 所有鍵名支援 camelCase（`maxTokens`）與 snake_case（`max_tokens`）兩種寫法，可在同一設定檔中混用。

---

## agents

Agent 行為的根節點，目前包含 `defaults` 子節點。

### agents.defaults

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `workspace` | string | `~/.nanobot/workspace` | Agent 工作目錄，支援 `~` 展開 |
| `model` | string | `anthropic/claude-opus-4-5` | 使用的 LLM 模型，格式為 `provider/model-name` |
| `provider` | string | `"auto"` | 強制指定供應商名稱，或 `"auto"` 自動依模型名稱比對 |
| `max_tokens` | integer | `8192` | 每次 LLM 呼叫的最大輸出 Token 數 |
| `context_window_tokens` | integer | `65536` | 對話脈絡視窗大小（Token 數），超過時觸發記憶體整合 |
| `temperature` | float | `0.1` | 取樣溫度，`0.0` 最確定，`1.0` 最隨機 |
| `max_tool_iterations` | integer | `40` | 單次請求中工具呼叫的最大迴圈次數，防止無限迴圈 |
| `reasoning_effort` | string \| null | `null` | 思考模式強度：`"low"`、`"medium"`、`"high"`，`null` 停用 |

#### workspace

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace"
    }
  }
}
```

Agent 會在此目錄讀寫檔案、執行 Shell 命令，以及儲存記憶體與工作階段資料。啟用 `tools.restrict_to_workspace` 後，所有工具存取均被沙箱限制在此目錄內。

#### model

```json
{
  "agents": {
    "defaults": {
      "model": "openrouter/anthropic/claude-opus-4-5"
    }
  }
}
```

模型字串格式與供應商有關：

| 格式 | 範例 | 適用場景 |
|------|------|----------|
| `provider/model` | `anthropic/claude-opus-4-5` | 標準 LiteLLM 格式 |
| `model-only` | `llama3.2` | 本地模型（Ollama） |
| 部署名稱 | `my-gpt4-deployment` | Azure OpenAI |

#### provider

```json
{
  "agents": {
    "defaults": {
      "provider": "ollama"
    }
  }
}
```

`"auto"`（預設）會依模型名稱前綴與關鍵字自動比對已設定的供應商。設為明確名稱（如 `"anthropic"`、`"openrouter"`）可強制路由，避免自動比對失誤。

#### reasoning_effort

```json
{
  "agents": {
    "defaults": {
      "reasoning_effort": "high"
    }
  }
}
```

啟用 LLM 的思考模式（Extended Thinking）。僅部分模型支援，例如 Claude 3.7 Sonnet 及更新版本。設為 `null` 或省略此欄位可停用。

---

## channels

聊天頻道的根節點。除全域選項外，每個平台的設定以平台名稱為鍵（如 `"telegram"`、`"slack"`）存放於此節點，各平台自行解析其設定內容。

### 全域頻道選項

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `send_progress` | bool | `true` | 是否將 Agent 的文字進度串流傳送至頻道 |
| `send_tool_hints` | bool | `false` | 是否傳送工具呼叫提示（例如 `read_file("…")`） |

```json
{
  "channels": {
    "send_progress": true,
    "send_tool_hints": false,
    "telegram": {
      "enabled": true,
      "token": "YOUR_BOT_TOKEN",
      "allowFrom": ["123456789"]
    }
  }
}
```

### 各平台共用欄位

大多數頻道支援以下欄位（各平台可能有額外欄位）：

| 欄位 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否啟用此頻道 |
| `allowFrom` | list[string] | `[]` | 允許傳送訊息的使用者 ID 白名單；空陣列拒絕全部，`["*"]` 允許全部 |

> [!WARNING]
> `allowFrom` 預設為空陣列，**拒絕所有使用者**。請務必設定允許的使用者 ID，否則 Bot 不會回應任何訊息。

---

## providers

LLM 供應商設定的根節點。每個供應商以其名稱為鍵，值為含 `api_key`、`api_base`、`extra_headers` 的物件。

### ProviderConfig 欄位

| 欄位 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `api_key` | string | `""` | API 金鑰 |
| `api_base` | string \| null | `null` | 自訂 API 端點 URL |
| `extra_headers` | dict \| null | `null` | 自訂 HTTP 標頭（例如 `APP-Code`） |

### 支援的供應商

| 供應商鍵 | 說明 | 取得 API 金鑰 |
|----------|------|--------------|
| `custom` | 任意 OpenAI 相容端點（直連，不經 LiteLLM） | — |
| `anthropic` | Claude 系列模型（直連） | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT 系列模型（直連） | [platform.openai.com](https://platform.openai.com) |
| `openrouter` | 所有模型的 API 閘道（推薦） | [openrouter.ai](https://openrouter.ai) |
| `azure_openai` | Azure OpenAI（model 欄位填部署名稱） | [portal.azure.com](https://portal.azure.com) |
| `deepseek` | DeepSeek 模型（直連） | [platform.deepseek.com](https://platform.deepseek.com) |
| `gemini` | Google Gemini（直連） | [aistudio.google.com](https://aistudio.google.com) |
| `groq` | Groq LLM + Whisper 語音轉文字 | [console.groq.com](https://console.groq.com) |
| `moonshot` | Moonshot / Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `minimax` | MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `zhipu` | 智譜 GLM | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `dashscope` | 阿里雲通義千問 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `siliconflow` | 硅基流動 | [siliconflow.cn](https://siliconflow.cn) |
| `aihubmix` | AiHubMix API 閘道 | [aihubmix.com](https://aihubmix.com) |
| `volcengine` | 火山引擎（按量付費） | [volcengine.com](https://www.volcengine.com) |
| `volcengine_coding_plan` | 火山引擎 Coding Plan（訂閱方案） | — |
| `byteplus` | BytePlus（火山引擎國際版，按量付費） | [byteplus.com](https://www.byteplus.com) |
| `byteplus_coding_plan` | BytePlus Coding Plan（訂閱方案） | — |
| `mistral` | Mistral AI | [console.mistral.ai](https://console.mistral.ai) |
| `ollama` | 本地 Ollama 模型 | — |
| `vllm` | 本地 vLLM 或任意 OpenAI 相容伺服器 | — |
| `openai_codex` | OpenAI Codex（OAuth，需 ChatGPT Plus/Pro） | `nanobot provider login openai-codex` |
| `github_copilot` | GitHub Copilot（OAuth） | `nanobot provider login github-copilot` |

### 範例

**Anthropic（直連）：**

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

**OpenRouter（存取所有模型）：**

```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    }
  },
  "agents": {
    "defaults": {
      "model": "openrouter/anthropic/claude-opus-4-5"
    }
  }
}
```

**自訂 OpenAI 相容端點：**

```json
{
  "providers": {
    "custom": {
      "apiKey": "your-api-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "your-model-name"
    }
  }
}
```

> [!TIP]
> 本地伺服器不需要金鑰時，可將 `apiKey` 設為任意非空字串（例如 `"no-key"`）。

**AiHubMix（需要 `extra_headers`）：**

```json
{
  "providers": {
    "aihubmix": {
      "apiKey": "your-key",
      "extraHeaders": {
        "APP-Code": "your-app-code"
      }
    }
  }
}
```

**Ollama（本地）：**

```json
{
  "providers": {
    "ollama": {
      "apiBase": "http://localhost:11434"
    }
  },
  "agents": {
    "defaults": {
      "provider": "ollama",
      "model": "llama3.2"
    }
  }
}
```

**特殊 API Base 設定：**

| 供應商 | 情境 | `apiBase` 值 |
|--------|------|-------------|
| `zhipu` | Coding Plan | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `minimax` | 中國大陸平台 | `https://api.minimaxi.com/v1` |
| `dashscope` | 阿里雲 BaiLian | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

---

## gateway

HTTP 閘道伺服器設定。

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | 監聽的網路介面，`"0.0.0.0"` 監聽所有介面 |
| `port` | integer | `18790` | 監聽的 TCP 埠號 |
| `heartbeat.enabled` | bool | `true` | 是否啟用心跳服務 |
| `heartbeat.interval_s` | integer | `1800` | 心跳間隔（秒），預設 30 分鐘 |

```json
{
  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  }
}
```

> [!TIP]
> 執行多個執行個體時，為每個執行個體指定不同的埠號，例如 `18790`、`18791`、`18792`。
> 也可在命令列以 `--port` 旗標臨時覆蓋：`nanobot gateway --port 18791`

---

## tools

工具設定的根節點，包含網路、Shell 執行、輸入限制與 MCP 伺服器。

### tools.web

網路工具設定。

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `proxy` | string \| null | `null` | HTTP/SOCKS5 代理 URL，路由所有網路請求（搜尋與擷取） |

```json
{
  "tools": {
    "web": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

支援格式：
- HTTP 代理：`"http://127.0.0.1:7890"`
- SOCKS5 代理：`"socks5://127.0.0.1:1080"`

### tools.web.search

網路搜尋工具設定。

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `provider` | string | `"brave"` | 搜尋後端：`"brave"`、`"tavily"`、`"duckduckgo"`、`"searxng"`、`"jina"` |
| `api_key` | string | `""` | Brave 或 Tavily 的 API 金鑰 |
| `base_url` | string | `""` | SearXNG 的自架 URL |
| `max_results` | integer | `5` | 每次搜尋回傳的結果數（建議範圍 1–10） |

#### 各搜尋供應商比較

| 供應商 | 需要金鑰 | 免費 | 環境變數備援 |
|--------|---------|------|------------|
| `brave`（預設） | 是 | 否 | `BRAVE_API_KEY` |
| `tavily` | 是 | 否 | `TAVILY_API_KEY` |
| `jina` | 是 | 有免費額度（1000 萬 Token） | `JINA_API_KEY` |
| `searxng` | 否（需自架） | 是 | `SEARXNG_BASE_URL` |
| `duckduckgo` | 否 | 是 | — |

> [!NOTE]
> 缺少憑證時，Nanobot 會自動降級使用 DuckDuckGo。

**Brave（預設）：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "brave",
        "apiKey": "BSA..."
      }
    }
  }
}
```

**Tavily：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "tavily",
        "apiKey": "tvly-..."
      }
    }
  }
}
```

**Jina（有免費額度）：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "jina",
        "apiKey": "jina_..."
      }
    }
  }
}
```

**SearXNG（自架，無需金鑰）：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "searxng",
        "baseUrl": "https://searx.example.com"
      }
    }
  }
}
```

**DuckDuckGo（免設定）：**

```json
{
  "tools": {
    "web": {
      "search": {
        "provider": "duckduckgo"
      }
    }
  }
}
```

### tools.exec

Shell 執行工具設定。

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `timeout` | integer | `60` | Shell 命令執行逾時（秒） |
| `path_append` | string | `""` | 執行 Shell 命令時附加到 `PATH` 的額外目錄 |

```json
{
  "tools": {
    "exec": {
      "timeout": 120,
      "pathAppend": "/usr/local/sbin:/usr/sbin"
    }
  }
}
```

> [!TIP]
> 若 Agent 找不到特定命令（如 `ufw`、`iptables`），可將其所在目錄加入 `path_append`。

### tools.input_limits

使用者提供的多模態輸入限制。

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `max_input_images` | integer | `3` | 單次請求允許的最大圖片數量 |
| `max_input_image_bytes` | integer | `10485760`（10 MB） | 單張圖片的最大位元組數 |

```json
{
  "tools": {
    "inputLimits": {
      "maxInputImages": 3,
      "maxInputImageBytes": 10485760
    }
  }
}
```

### tools.restrict_to_workspace

| 選項 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `restrict_to_workspace` | bool | `false` | 若為 `true`，所有工具存取（Shell、檔案讀寫）均被限制在工作區目錄內 |

```json
{
  "tools": {
    "restrictToWorkspace": true
  }
}
```

> [!WARNING]
> 生產環境部署建議啟用此選項，防止路徑遍歷與越界存取。

### tools.mcp_servers

MCP（Model Context Protocol）伺服器設定，以伺服器名稱為鍵的字典。

> [!TIP]
> 設定格式與 Claude Desktop / Cursor 相容，可直接複製 MCP 伺服器 README 中的設定。

#### MCPServerConfig 欄位

| 欄位 | 型別 | 預設值 | 說明 |
|------|------|--------|------|
| `type` | `"stdio"` \| `"sse"` \| `"streamableHttp"` \| null | `null` | 傳輸類型，省略時自動偵測 |
| `command` | string | `""` | **Stdio 模式**：要執行的命令（例如 `"npx"`） |
| `args` | list[string] | `[]` | **Stdio 模式**：命令引數 |
| `env` | dict[string, string] | `{}` | **Stdio 模式**：額外環境變數 |
| `url` | string | `""` | **HTTP/SSE 模式**：端點 URL |
| `headers` | dict[string, string] | `{}` | **HTTP/SSE 模式**：自訂 HTTP 標頭 |
| `tool_timeout` | integer | `30` | 單次工具呼叫的逾時秒數 |
| `enabled_tools` | list[string] | `["*"]` | 要註冊的工具清單；`["*"]` 為全部，`[]` 為不註冊 |

#### 傳輸模式

| 模式 | 使用欄位 | 範例 |
|------|----------|------|
| **Stdio** | `command` + `args` | 透過 `npx` / `uvx` 啟動本地程序 |
| **HTTP** | `url` + `headers`（可選） | 遠端端點（`https://mcp.example.com/sse`） |

#### Stdio 範例

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
      },
      "git": {
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "/path/to/repo"]
      }
    }
  }
}
```

#### HTTP / SSE 範例

```json
{
  "tools": {
    "mcpServers": {
      "my-remote-mcp": {
        "url": "https://example.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

#### 自訂逾時

```json
{
  "tools": {
    "mcpServers": {
      "slow-server": {
        "url": "https://example.com/mcp/",
        "toolTimeout": 120
      }
    }
  }
}
```

#### 篩選工具

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "enabledTools": ["read_file", "mcp_filesystem_write_file"]
      }
    }
  }
}
```

`enabledTools` 接受原始 MCP 工具名稱（`read_file`）或 Nanobot 包裝後的名稱（`mcp_filesystem_write_file`）。

| `enabledTools` 值 | 行為 |
|-------------------|------|
| `["*"]`（預設）或省略 | 註冊所有工具 |
| `[]` | 不註冊任何工具 |
| `["tool_a", "tool_b"]` | 僅註冊指定工具 |

---

## 完整設定範例

以下為包含所有選項的完整設定範例（含說明用偽註解，**實際 JSON 不支援 `//` 註解**）：

```json
{
  "agents": {
    "defaults": {
      "workspace": "~/.nanobot/workspace",
      "model": "anthropic/claude-opus-4-5",
      "provider": "auto",
      "maxTokens": 8192,
      "contextWindowTokens": 65536,
      "temperature": 0.1,
      "maxToolIterations": 40,
      "reasoningEffort": null
    }
  },

  "channels": {
    "sendProgress": true,
    "sendToolHints": false,

    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": ["YOUR_TELEGRAM_USER_ID"]
    },

    "slack": {
      "enabled": false,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["U01234567"]
    },

    "discord": {
      "enabled": false,
      "token": "YOUR_DISCORD_BOT_TOKEN",
      "allowFrom": ["123456789012345678"]
    }
  },

  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    },
    "openai": {
      "apiKey": "sk-..."
    },
    "openrouter": {
      "apiKey": "sk-or-v1-..."
    },
    "deepseek": {
      "apiKey": "sk-..."
    },
    "gemini": {
      "apiKey": "AIza..."
    },
    "groq": {
      "apiKey": "gsk_..."
    },
    "ollama": {
      "apiBase": "http://localhost:11434"
    },
    "custom": {
      "apiKey": "your-key",
      "apiBase": "https://api.your-provider.com/v1"
    }
  },

  "gateway": {
    "host": "0.0.0.0",
    "port": 18790,
    "heartbeat": {
      "enabled": true,
      "intervalS": 1800
    }
  },

  "tools": {
    "web": {
      "proxy": null,
      "search": {
        "provider": "brave",
        "apiKey": "BSA...",
        "baseUrl": "",
        "maxResults": 5
      }
    },
    "exec": {
      "timeout": 60,
      "pathAppend": ""
    },
    "inputLimits": {
      "maxInputImages": 3,
      "maxInputImageBytes": 10485760
    },
    "restrictToWorkspace": false,
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
        "toolTimeout": 30,
        "enabledTools": ["*"]
      },
      "remote-api": {
        "url": "https://mcp.example.com/sse",
        "headers": {
          "Authorization": "Bearer token"
        },
        "toolTimeout": 60,
        "enabledTools": ["search", "fetch"]
      }
    }
  }
}
```
