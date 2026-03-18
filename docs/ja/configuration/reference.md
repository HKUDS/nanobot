# 設定リファレンス（全項目）

このページでは `~/.nanobot/config.json` にある全ての設定オプションについて、型・デフォルト値・説明をまとめます。

> [!NOTE]
> すべてのキー名は camelCase（`maxTokens`）と snake_case（`max_tokens`）の両方をサポートし、同一の設定ファイル内で混在させられます。

---

## agents

エージェント挙動のルート設定です。現在は `defaults` サブノードを含みます。

### agents.defaults

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `workspace` | string | `~/.nanobot/workspace` | エージェントの作業ディレクトリ。`~` の展開に対応 |
| `model` | string | `anthropic/claude-opus-4-5` | 使用する LLM モデル。形式は `provider/model-name` |
| `provider` | string | `"auto"` | プロバイダ名を強制指定、または `"auto"` でモデル名から自動マッチ |
| `max_tokens` | integer | `8192` | 1 回の LLM 呼び出しでの最大出力トークン数 |
| `context_window_tokens` | integer | `65536` | 会話コンテキストのウィンドウサイズ（トークン数）。超過時はメモリ統合を実行 |
| `temperature` | float | `0.1` | サンプリング温度。`0.0` が最も確定的、`1.0` が最もランダム |
| `max_tool_iterations` | integer | `40` | 1 回のリクエスト内でのツール呼び出し最大ループ回数（無限ループ防止） |
| `reasoning_effort` | string \| null | `null` | 思考モード強度：`"low"` / `"medium"` / `"high"`。`null` で無効 |

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

エージェントはこのディレクトリ内でファイルの読み書き、シェルコマンドの実行、メモリやセッションデータの保存を行います。`tools.restrict_to_workspace` を有効化すると、すべてのツールアクセスがこのディレクトリ内にサンドボックス化されます。

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

モデル文字列の形式はプロバイダによって異なります：

| 形式 | 例 | 適用シーン |
|------|------|----------|
| `provider/model` | `anthropic/claude-opus-4-5` | 標準の LiteLLM 形式 |
| `model-only` | `llama3.2` | ローカルモデル（Ollama） |
| デプロイ名 | `my-gpt4-deployment` | Azure OpenAI |

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

`"auto"`（デフォルト）は、モデル名のプレフィックスやキーワードから設定済みプロバイダを自動的にマッチさせます。明示的な名前（例：`"anthropic"`、`"openrouter"`）を指定すると、誤マッチを避けて強制的にルーティングできます。

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

LLM の思考モード（Extended Thinking）を有効化します。対応するのは一部のモデルのみ（例：Claude 3.7 Sonnet 以降）です。`null` を設定するか、このフィールドを省略すると無効になります。

---

## channels

チャットチャネルのルート設定です。グローバルオプションに加え、各プラットフォームの設定はプラットフォーム名（例：`"telegram"`、`"slack"`）をキーとしてこのノード配下に置かれ、各プラットフォームがそれぞれ内容を解釈します。

### グローバルチャネルオプション

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `send_progress` | bool | `true` | エージェントのテキスト進捗をストリーミング送信するか |
| `send_tool_hints` | bool | `false` | ツール呼び出しヒント（例：`read_file("…")`）を送信するか |

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

### 各プラットフォーム共通フィールド

多くのチャネルは以下のフィールドをサポートします（プラットフォームによって追加フィールドがある場合があります）：

| フィールド | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `enabled` | bool | `false` | このチャネルを有効化するか |
| `allowFrom` | list[string] | `[]` | メッセージ送信を許可するユーザー ID のホワイトリスト。空配列は全拒否、`["*"]` は全許可 |

> [!WARNING]
> `allowFrom` のデフォルトは空配列で、**すべてのユーザーを拒否**します。必ず許可するユーザー ID を設定してください。設定しない場合、Bot はどのメッセージにも応答しません。

---

## providers

LLM プロバイダ設定のルートノードです。各プロバイダはその名前をキーに持ち、値は `api_key` / `api_base` / `extra_headers` を含むオブジェクトです。

### ProviderConfig フィールド

| フィールド | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `api_key` | string | `""` | API キー |
| `api_base` | string \| null | `null` | カスタム API エンドポイント URL |
| `extra_headers` | dict \| null | `null` | カスタム HTTP ヘッダー（例：`APP-Code`） |

### 対応プロバイダ

| プロバイダキー | 説明 | API キーの取得 |
|----------|------|--------------|
| `custom` | 任意の OpenAI 互換エンドポイント（直結、LiteLLM 経由ではない） | — |
| `anthropic` | Claude 系モデル（直結） | [console.anthropic.com](https://console.anthropic.com) |
| `openai` | GPT 系モデル（直結） | [platform.openai.com](https://platform.openai.com) |
| `openrouter` | 全モデル対応の API ゲートウェイ（推奨） | [openrouter.ai](https://openrouter.ai) |
| `azure_openai` | Azure OpenAI（`model` にはデプロイ名を指定） | [portal.azure.com](https://portal.azure.com) |
| `deepseek` | DeepSeek モデル（直結） | [platform.deepseek.com](https://platform.deepseek.com) |
| `gemini` | Google Gemini（直結） | [aistudio.google.com](https://aistudio.google.com) |
| `groq` | Groq LLM + Whisper 音声文字起こし | [console.groq.com](https://console.groq.com) |
| `moonshot` | Moonshot / Kimi | [platform.moonshot.cn](https://platform.moonshot.cn) |
| `minimax` | MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `zhipu` | 智譜 GLM | [open.bigmodel.cn](https://open.bigmodel.cn) |
| `dashscope` | 阿里雲 通義千問 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `siliconflow` | 硅基流動 | [siliconflow.cn](https://siliconflow.cn) |
| `aihubmix` | AiHubMix API ゲートウェイ | [aihubmix.com](https://aihubmix.com) |
| `volcengine` | 火山引擎（従量課金） | [volcengine.com](https://www.volcengine.com) |
| `volcengine_coding_plan` | 火山引擎 Coding Plan（サブスクリプション） | — |
| `byteplus` | BytePlus（火山引擎の国際版、従量課金） | [byteplus.com](https://www.byteplus.com) |
| `byteplus_coding_plan` | BytePlus Coding Plan（サブスクリプション） | — |
| `mistral` | Mistral AI | [console.mistral.ai](https://console.mistral.ai) |
| `ollama` | ローカル Ollama モデル | — |
| `vllm` | ローカル vLLM または任意の OpenAI 互換サーバ | — |
| `openai_codex` | OpenAI Codex（OAuth。ChatGPT Plus/Pro が必要） | `nanobot provider login openai-codex` |
| `github_copilot` | GitHub Copilot（OAuth） | `nanobot provider login github-copilot` |

### 例

**Anthropic（直結）：**

```json
{
  "providers": {
    "anthropic": {
      "apiKey": "sk-ant-..."
    }
  }
}
```

**OpenRouter（全モデルにアクセス）：**

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

**カスタム OpenAI 互換エンドポイント：**

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
> ローカルサーバでキーが不要な場合でも、`apiKey` を任意の空でない文字列（例：`"no-key"`）にしてください。

**AiHubMix（`extra_headers` が必要）：**

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

**Ollama（ローカル）：**

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

**特殊な API Base 設定：**

| プロバイダ | シーン | `apiBase` の値 |
|--------|------|-------------|
| `zhipu` | Coding Plan | `https://open.bigmodel.cn/api/coding/paas/v4` |
| `minimax` | 中国本土プラットフォーム | `https://api.minimaxi.com/v1` |
| `dashscope` | 阿里雲 BaiLian | `https://dashscope.aliyuncs.com/compatible-mode/v1` |

---

## gateway

HTTP ゲートウェイサーバの設定です。

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `host` | string | `"0.0.0.0"` | 待ち受けるネットワークインターフェース。`"0.0.0.0"` は全インターフェース |
| `port` | integer | `18790` | 待ち受ける TCP ポート |
| `heartbeat.enabled` | bool | `true` | ハートビートを有効化するか |
| `heartbeat.interval_s` | integer | `1800` | ハートビート間隔（秒）。デフォルト 30 分 |

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
> 複数インスタンスを実行する場合は、インスタンスごとに異なるポート（例：`18790`、`18791`、`18792`）を指定してください。
> コマンドラインでも `--port` フラグで一時的に上書きできます：`nanobot gateway --port 18791`

---

## tools

ツール設定のルートノードです。ネットワーク、シェル実行、入力制限、MCP サーバなどを含みます。

### tools.web

Web ツールの設定です。

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `proxy` | string \| null | `null` | HTTP/SOCKS5 プロキシ URL。すべての Web リクエスト（検索と取得）をプロキシ経由にする |

```json
{
  "tools": {
    "web": {
      "proxy": "http://127.0.0.1:7890"
    }
  }
}
```

対応形式：
- HTTP プロキシ：`"http://127.0.0.1:7890"`
- SOCKS5 プロキシ：`"socks5://127.0.0.1:1080"`

### tools.web.search

Web 検索ツールの設定です。

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `provider` | string | `"brave"` | 検索バックエンド：`"brave"` / `"tavily"` / `"duckduckgo"` / `"searxng"` / `"jina"` |
| `api_key` | string | `""` | Brave または Tavily の API キー |
| `base_url` | string | `""` | SearXNG のセルフホスト URL |
| `max_results` | integer | `5` | 1 回の検索で返す結果数（推奨 1–10） |

#### 検索プロバイダ比較

| プロバイダ | キーが必要 | 無料 | 環境変数フォールバック |
|--------|---------|------|------------|
| `brave`（デフォルト） | はい | いいえ | `BRAVE_API_KEY` |
| `tavily` | はい | いいえ | `TAVILY_API_KEY` |
| `jina` | はい | 無料枠あり（1000 万トークン） | `JINA_API_KEY` |
| `searxng` | いいえ（要セルフホスト） | はい | `SEARXNG_BASE_URL` |
| `duckduckgo` | いいえ | はい | — |

> [!NOTE]
> 認証情報が無い場合、Nanobot は自動的に DuckDuckGo にフォールバックします。

**Brave（デフォルト）：**

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

**Jina（無料枠あり）：**

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

**SearXNG（セルフホスト、キー不要）：**

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

**DuckDuckGo（設定不要）：**

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

シェル実行ツールの設定です。

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `timeout` | integer | `60` | シェルコマンド実行のタイムアウト（秒） |
| `path_append` | string | `""` | シェル実行時に `PATH` へ追加するディレクトリ |

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
> エージェントが特定コマンド（例：`ufw`、`iptables`）を見つけられない場合は、その配置ディレクトリを `path_append` に追加してください。

### tools.input_limits

ユーザー提供のマルチモーダル入力の制限です。

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `max_input_images` | integer | `3` | 1 リクエストで許可する最大画像数 |
| `max_input_image_bytes` | integer | `10485760`（10 MB） | 1 枚あたりの最大バイト数 |

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

| オプション | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `restrict_to_workspace` | bool | `false` | `true` の場合、すべてのツールアクセス（シェル、ファイル I/O）をワークスペース内に制限 |

```json
{
  "tools": {
    "restrictToWorkspace": true
  }
}
```

> [!WARNING]
> 本番環境でのデプロイでは、このオプションを有効化してパストラバーサルやスコープ外アクセスを防ぐことを推奨します。

### tools.mcp_servers

MCP（Model Context Protocol）サーバの設定です。サーバ名をキーにした辞書として指定します。

> [!TIP]
> 設定形式は Claude Desktop / Cursor と互換です。MCP サーバの README にある設定をそのままコピーできます。

#### MCPServerConfig フィールド

| フィールド | 型 | デフォルト | 説明 |
|------|------|--------|------|
| `type` | `"stdio"` \| `"sse"` \| `"streamableHttp"` \| null | `null` | トランスポート種別。省略時は自動検出 |
| `command` | string | `""` | **Stdio モード**：実行するコマンド（例：`"npx"`） |
| `args` | list[string] | `[]` | **Stdio モード**：コマンド引数 |
| `env` | dict[string, string] | `{}` | **Stdio モード**：追加環境変数 |
| `url` | string | `""` | **HTTP/SSE モード**：エンドポイント URL |
| `headers` | dict[string, string] | `{}` | **HTTP/SSE モード**：カスタム HTTP ヘッダー |
| `tool_timeout` | integer | `30` | 1 回のツール呼び出しタイムアウト（秒） |
| `enabled_tools` | list[string] | `["*"]` | 登録するツール一覧。`["*"]` は全て、`[]` は登録なし |

#### トランスポート

| モード | 使用フィールド | 例 |
|------|----------|------|
| **Stdio** | `command` + `args` | `npx` / `uvx` でローカルプロセス起動 |
| **HTTP** | `url` + `headers`（任意） | リモートエンドポイント（`https://mcp.example.com/sse`） |

#### Stdio の例

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

#### HTTP / SSE の例

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

#### タイムアウトのカスタマイズ

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

#### ツールのフィルタリング

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

`enabledTools` は、元の MCP ツール名（`read_file`）または Nanobot でラップされた名前（`mcp_filesystem_write_file`）のどちらも指定できます。

| `enabledTools` の値 | 挙動 |
|-------------------|------|
| `["*"]`（デフォルト）または省略 | 全ツールを登録 |
| `[]` | いずれのツールも登録しない |
| `["tool_a", "tool_b"]` | 指定ツールのみ登録 |

---

## 設定の完全例

以下は、すべてのオプションを含む完全な設定例です（説明用の擬似コメントを含みます。**実際の JSON は `//` コメントをサポートしません**）：

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
