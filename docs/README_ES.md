<div align="center">
  <img src="../nanobot_logo.png" alt="nanobot" width="500">
  <h1>nanobot: Asistente Personal de IA Ultra-Ligero</h1>
  <p>
    <a href="https://pypi.org/project/nanobot-ai/"><img src="https://img.shields.io/pypi/v/nanobot-ai" alt="PyPI"></a>
    <a href="https://pepy.tech/project/nanobot-ai"><img src="https://static.pepy.tech/badge/nanobot-ai" alt="Descargas"></a>
    <img src="https://img.shields.io/badge/python-≥3.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/licencia-MIT-green" alt="Licencia">
    <a href="../COMMUNICATION.md"><img src="https://img.shields.io/badge/Feishu-Grupo-E9DBFC?style=flat&logo=feishu&logoColor=white" alt="Feishu"></a>
    <a href="../COMMUNICATION.md"><img src="https://img.shields.io/badge/WeChat-Grupo-C5EAB4?style=flat&logo=wechat&logoColor=white" alt="WeChat"></a>
    <a href="https://discord.gg/MnCvHqpUGB"><img src="https://img.shields.io/badge/Discord-Comunidad-5865F2?style=flat&logo=discord&logoColor=white" alt="Discord"></a>
  </p>
  <p>
    <a href="../README.md">English</a> · <b>Español</b>
  </p>
</div>

🐈 **nanobot** es un asistente personal de IA **ultra-ligero** inspirado en [OpenClaw](https://github.com/openclaw/openclaw).

⚡️ Ofrece la funcionalidad principal de un agente con **99% menos líneas de código** que OpenClaw.

📏 Conteo de líneas en tiempo real: ejecuta `bash core_agent_lines.sh` para verificar en cualquier momento.

## 📢 Noticias

> [!IMPORTANT]
> **Nota de seguridad:** Debido al envenenamiento de la cadena de suministro de `litellm`, **revisa tu entorno Python lo antes posible** y consulta este [aviso](https://github.com/HKUDS/nanobot/discussions/2445) para más detalles. Hemos eliminado completamente `litellm` desde **v0.1.4.post6**.

- **2026-03-27** 🚀 Lanzamiento de **v0.1.4.post6** — desacoplamiento de arquitectura, eliminación de litellm, streaming de extremo a extremo, canal WeChat y una corrección de seguridad. Consulta las [notas de lanzamiento](https://github.com/HKUDS/nanobot/releases/tag/v0.1.4.post6) para más detalles.

> 🐈 nanobot es solo para fines educativos, de investigación e intercambio técnico. No está relacionado con criptomonedas y no involucra ningún token o moneda oficial.

## Características principales de nanobot:

🪶 **Ultra-Ligero**: Una implementación super ligera de OpenClaw — 99% más pequeña, significativamente más rápida.

🔬 **Listo para Investigación**: Código limpio y legible, fácil de entender, modificar y extender para investigación.

⚡️ **Veloz como un Rayo**: Mínima huella significa arranque más rápido, menor uso de recursos e iteraciones más rápidas.

💎 **Fácil de Usar**: Un clic para desplegar y estás listo.

## 🏗️ Arquitectura

<p align="center">
  <img src="../nanobot_arch.png" alt="arquitectura de nanobot" width="800">
</p>

## Tabla de Contenidos

- [Noticias](#-noticias)
- [Características principales](#características-principales-de-nanobot)
- [Arquitectura](#️-arquitectura)
- [Funcionalidades](#-funcionalidades)
- [Instalación](#-instalación)
- [Inicio Rápido](#-inicio-rápido)
- [Apps de Chat](#-apps-de-chat)
- [Red Social de Agentes](#-red-social-de-agentes)
- [Configuración](#️-configuración)
- [Múltiples Instancias](#-múltiples-instancias)
- [Referencia CLI](#-referencia-cli)
- [SDK Python](#-sdk-python)
- [API Compatible con OpenAI](#-api-compatible-con-openai)
- [Docker](#-docker)
- [Servicio Linux](#-servicio-linux)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Contribuir y Roadmap](#-contribuir--roadmap)

## ✨ Funcionalidades

<table align="center">
  <tr align="center">
    <th><p align="center">📈 Análisis de Mercado 24/7</p></th>
    <th><p align="center">🚀 Ingeniero de Software Full-Stack</p></th>
    <th><p align="center">📅 Gestor de Rutina Diaria Inteligente</p></th>
    <th><p align="center">📚 Asistente de Conocimiento Personal</p></th>
  </tr>
  <tr>
    <td align="center"><p align="center"><img src="../case/search.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="../case/code.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="../case/scedule.gif" width="180" height="400"></p></td>
    <td align="center"><p align="center"><img src="../case/memory.gif" width="180" height="400"></p></td>
  </tr>
  <tr>
    <td align="center">Descubrimiento • Insights • Tendencias</td>
    <td align="center">Desarrollar • Desplegar • Escalar</td>
    <td align="center">Agendar • Automatizar • Organizar</td>
    <td align="center">Aprender • Memoria • Razonamiento</td>
  </tr>
</table>

## 📦 Instalación

**Instalar desde código fuente** (últimas funciones, recomendado para desarrollo)

```bash
git clone https://github.com/HKUDS/nanobot.git
cd nanobot
pip install -e .
```

**Instalar con [uv](https://github.com/astral-sh/uv)** (estable, rápido)

```bash
uv tool install nanobot-ai
```

**Instalar desde PyPI** (estable)

```bash
pip install nanobot-ai
```

### Actualizar a la última versión

**PyPI / pip**

```bash
pip install -U nanobot-ai
nanobot --version
```

**uv**

```bash
uv tool upgrade nanobot-ai
nanobot --version
```

**¿Usas WhatsApp?** Reconstruye el bridge local después de actualizar:

```bash
rm -rf ~/.nanobot/bridge
nanobot channels login whatsapp
```

## 🚀 Inicio Rápido

> [!TIP]
> Configura tu API key en `~/.nanobot/config.json`.
> Obtén API keys: [OpenRouter](https://openrouter.ai/keys) (Global)
>
> Para otros proveedores LLM, consulta la sección [Proveedores](#proveedores).
>
> Para configurar búsqueda web, consulta [Búsqueda Web](#búsqueda-web).

**1. Inicializar**

```bash
nanobot onboard
```

Usa `nanobot onboard --wizard` si quieres el asistente de configuración interactivo.

**2. Configurar** (`~/.nanobot/config.json`)

Configura estas **dos partes** en tu config (las demás opciones tienen valores por defecto).

*Configura tu API key* (ej. OpenRouter, recomendado para usuarios globales):
```json
{
  "providers": {
    "openrouter": {
      "apiKey": "sk-or-v1-xxx"
    }
  }
}
```

*Configura tu modelo* (opcionalmente fija un proveedor — por defecto es auto-detección):
```json
{
  "agents": {
    "defaults": {
      "model": "anthropic/claude-opus-4-5",
      "provider": "openrouter"
    }
  }
}
```

**3. Chatear**

```bash
nanobot agent
```

¡Eso es todo! Tienes un asistente de IA funcionando en 2 minutos.

## 💬 Apps de Chat

Conecta nanobot a tu plataforma de chat favorita. ¿Quieres construir la tuya propia? Consulta la [Guía de Plugins de Canal](./CHANNEL_PLUGIN_GUIDE.md).

| Canal | Lo que necesitas |
|-------|-----------------|
| **Telegram** | Token de bot de @BotFather |
| **Discord** | Token de bot + Message Content intent |
| **WhatsApp** | Escaneo de código QR (`nanobot channels login whatsapp`) |
| **WeChat (Weixin)** | Escaneo de código QR (`nanobot channels login weixin`) |
| **Feishu** | App ID + App Secret |
| **DingTalk** | App Key + App Secret |
| **Slack** | Bot token + App-Level token |
| **Matrix** | URL del Homeserver + Access token |
| **Email** | Credenciales IMAP/SMTP |
| **QQ** | App ID + App Secret |
| **Wecom** | Bot ID + Bot Secret |
| **Mochat** | Token Claw (configuración automática disponible) |

<details>
<summary><b>Telegram</b> (Recomendado)</summary>

**1. Crear un bot**
- Abre Telegram, busca `@BotFather`
- Envía `/newbot`, sigue las instrucciones
- Copia el token

**2. Configurar**

```json
{
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "TU_TOKEN_DE_BOT",
      "allowFrom": ["TU_USER_ID"]
    }
  }
}
```

> Puedes encontrar tu **User ID** en la configuración de Telegram. Se muestra como `@tuUserId`.
> Copia este valor **sin el símbolo `@`** y pégalo en el archivo de configuración.

**3. Ejecutar**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>Mochat (Claw IM)</b></summary>

Usa **WebSocket Socket.IO** por defecto, con respaldo a polling HTTP.

**1. Pide a nanobot que configure Mochat por ti**

Simplemente envía este mensaje a nanobot (reemplaza `xxx@xxx` con tu email real):

```
Read https://raw.githubusercontent.com/HKUDS/MoChat/refs/heads/main/skills/nanobot/skill.md and register on MoChat. My Email account is xxx@xxx Bind me as your owner and DM me on MoChat.
```

nanobot se registrará automáticamente, configurará `~/.nanobot/config.json` y se conectará a Mochat.

**2. Reiniciar gateway**

```bash
nanobot gateway
```

¡Eso es todo — nanobot se encarga del resto!

</details>

<details>
<summary><b>Discord</b></summary>

**1. Crear un bot**
- Ve a https://discord.com/developers/applications
- Crea una aplicación → Bot → Add Bot
- Copia el token del bot

**2. Habilitar intents**
- En la configuración del Bot, habilita **MESSAGE CONTENT INTENT**

**3. Obtener tu User ID**
- Configuración de Discord → Avanzado → habilita **Modo Desarrollador**
- Clic derecho en tu avatar → **Copiar ID de usuario**

**4. Configurar**

```json
{
  "channels": {
    "discord": {
      "enabled": true,
      "token": "TU_TOKEN_DE_BOT",
      "allowFrom": ["TU_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

> `groupPolicy` controla cómo responde el bot en canales de grupo:
> - `"mention"` (por defecto) — Solo responde cuando se le @menciona
> - `"open"` — Responde a todos los mensajes
> Los DMs siempre responden cuando el remitente está en `allowFrom`.

**5. Invitar al bot**
- OAuth2 → URL Generator
- Scopes: `bot`
- Bot Permissions: `Send Messages`, `Read Message History`
- Abre la URL generada y agrega el bot a tu servidor

**6. Ejecutar**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WhatsApp</b></summary>

Requiere **Node.js ≥18**.

**1. Vincular dispositivo**

```bash
nanobot channels login whatsapp
# Escanea el QR con WhatsApp → Configuración → Dispositivos Vinculados
```

**2. Configurar**

```json
{
  "channels": {
    "whatsapp": {
      "enabled": true,
      "allowFrom": ["+521234567890"]
    }
  }
}
```

**3. Ejecutar** (dos terminales)

```bash
# Terminal 1
nanobot channels login whatsapp

# Terminal 2
nanobot gateway
```

> Las actualizaciones del bridge de WhatsApp no se aplican automáticamente.
> Después de actualizar nanobot, reconstruye el bridge local con:
> `rm -rf ~/.nanobot/bridge && nanobot channels login whatsapp`

</details>

<details>
<summary><b>Feishu</b></summary>

Usa conexión larga **WebSocket** — no se requiere IP pública.

**1. Crear un bot de Feishu**
- Visita [Feishu Open Platform](https://open.feishu.cn/app)
- Crea una nueva app → Habilita la capacidad de **Bot**
- **Permisos**:
  - `im:message` (enviar mensajes) e `im:message.p2p_msg:readonly` (recibir mensajes)
  - **Respuestas con streaming**: agrega **`cardkit:card:write`**
- **Eventos**: Agrega `im.message.receive_v1` (recibir mensajes)
  - Selecciona modo **Long Connection**
- Obtén **App ID** y **App Secret** de "Credentials & Basic Info"
- Publica la app

**2. Configurar**

```json
{
  "channels": {
    "feishu": {
      "enabled": true,
      "appId": "cli_xxx",
      "appSecret": "xxx",
      "allowFrom": ["ou_TU_OPEN_ID"],
      "groupPolicy": "mention",
      "streaming": true
    }
  }
}
```

**3. Ejecutar**

```bash
nanobot gateway
```

> [!TIP]
> Feishu usa WebSocket para recibir mensajes — ¡no se necesita webhook ni IP pública!

</details>

<details>
<summary><b>Slack</b></summary>

Usa **Socket Mode** — no se requiere URL pública.

**1. Crear una app de Slack**
- Ve a [Slack API](https://api.slack.com/apps) → **Create New App** → "From scratch"
- Elige un nombre y selecciona tu workspace

**2. Configurar la app**
- **Socket Mode**: Activa → Genera un **App-Level Token** con scope `connections:write` → cópialo (`xapp-...`)
- **OAuth & Permissions**: Agrega bot scopes: `chat:write`, `reactions:write`, `app_mentions:read`
- **Event Subscriptions**: Activa → Suscríbete a bot events: `message.im`, `message.channels`, `app_mention`
- **App Home**: Ve a **Show Tabs** → Habilita **Messages Tab** → Marca **"Allow users to send Slash commands and messages from the messages tab"**
- **Install App**: Click **Install to Workspace** → Autoriza → copia el **Bot Token** (`xoxb-...`)

**3. Configurar nanobot**

```json
{
  "channels": {
    "slack": {
      "enabled": true,
      "botToken": "xoxb-...",
      "appToken": "xapp-...",
      "allowFrom": ["TU_SLACK_USER_ID"],
      "groupPolicy": "mention"
    }
  }
}
```

**4. Ejecutar**

```bash
nanobot gateway
```

Envía un DM al bot o @menciónalo en un canal — ¡debería responder!

</details>

<details>
<summary><b>Email</b></summary>

Dale a nanobot su propia cuenta de email. Revisa **IMAP** para correos entrantes y responde vía **SMTP** — como un asistente personal de email.

**1. Obtener credenciales (ejemplo con Gmail)**
- Crea una cuenta de Gmail dedicada para tu bot (ej. `mi-nanobot@gmail.com`)
- Habilita Verificación en 2 Pasos → Crea una [Contraseña de Aplicación](https://myaccount.google.com/apppasswords)

**2. Configurar**

```json
{
  "channels": {
    "email": {
      "enabled": true,
      "consentGranted": true,
      "imapHost": "imap.gmail.com",
      "imapPort": 993,
      "imapUsername": "mi-nanobot@gmail.com",
      "imapPassword": "tu-contraseña-de-app",
      "smtpHost": "smtp.gmail.com",
      "smtpPort": 587,
      "smtpUsername": "mi-nanobot@gmail.com",
      "smtpPassword": "tu-contraseña-de-app",
      "fromAddress": "mi-nanobot@gmail.com",
      "allowFrom": ["tu-email-real@gmail.com"]
    }
  }
}
```

**3. Ejecutar**

```bash
nanobot gateway
```

</details>

<details>
<summary><b>WeChat (微信 / Weixin)</b></summary>

Usa **HTTP long-poll** con login por código QR vía la API personal WeChat de ilinkai. No se requiere cliente de escritorio de WeChat.

**1. Instalar con soporte WeChat**

```bash
pip install "nanobot-ai[weixin]"
```

**2. Configurar**

```json
{
  "channels": {
    "weixin": {
      "enabled": true,
      "allowFrom": ["TU_WECHAT_USER_ID"]
    }
  }
}
```

**3. Iniciar sesión**

```bash
nanobot channels login weixin
```

**4. Ejecutar**

```bash
nanobot gateway
```

</details>

## 🌐 Red Social de Agentes

🐈 nanobot es capaz de conectarse a la red social de agentes (comunidad de agentes). **¡Solo envía un mensaje y tu nanobot se une automáticamente!**

| Plataforma | Cómo unirse (envía este mensaje a tu bot) |
|------------|------------------------------------------|
| [**Moltbook**](https://www.moltbook.com/) | `Read https://moltbook.com/skill.md and follow the instructions to join Moltbook` |
| [**ClawdChat**](https://clawdchat.ai/) | `Read https://clawdchat.ai/skill.md and follow the instructions to join ClawdChat` |

Simplemente envía el comando de arriba a tu nanobot (vía CLI o cualquier canal de chat), y él se encargará del resto.

## ⚙️ Configuración

Archivo de configuración: `~/.nanobot/config.json`

### Proveedores

> [!TIP]
> - **Groq** proporciona transcripción de voz gratuita vía Whisper. Si está configurado, los mensajes de voz de Telegram se transcribirán automáticamente.
> - **MiniMax Plan Coding**: Enlaces de descuento exclusivos para la comunidad nanobot: [Internacional](https://platform.minimax.io/subscribe/coding-plan?code=9txpdXw04g&source=link) · [China Continental](https://platform.minimaxi.com/subscribe/token-plan?code=GILTJpMTqZ&source=link)

| Proveedor | Propósito | Obtener API Key |
|-----------|-----------|----------------|
| `custom` | Cualquier endpoint compatible con OpenAI | — |
| `openrouter` | LLM (recomendado, acceso a todos los modelos) | [openrouter.ai](https://openrouter.ai) |
| `volcengine` | LLM (VolcEngine, pago por uso) | [volcengine.com](https://www.volcengine.com) |
| `anthropic` | LLM (Claude directo) | [console.anthropic.com](https://console.anthropic.com) |
| `azure_openai` | LLM (Azure OpenAI) | [portal.azure.com](https://portal.azure.com) |
| `openai` | LLM (GPT directo) | [platform.openai.com](https://platform.openai.com) |
| `deepseek` | LLM (DeepSeek directo) | [platform.deepseek.com](https://platform.deepseek.com) |
| `groq` | LLM + **Transcripción de voz** (Whisper) | [console.groq.com](https://console.groq.com) |
| `minimax` | LLM (MiniMax directo) | [platform.minimaxi.com](https://platform.minimaxi.com) |
| `gemini` | LLM (Gemini directo) | [aistudio.google.com](https://aistudio.google.com) |
| `siliconflow` | LLM (SiliconFlow/硅基流动) | [siliconflow.cn](https://siliconflow.cn) |
| `dashscope` | LLM (Qwen) | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com) |
| `ollama` | LLM (local, Ollama) | — |
| `mistral` | LLM | [docs.mistral.ai](https://docs.mistral.ai/) |
| `vllm` | LLM (local, cualquier servidor compatible con OpenAI) | — |
| `openai_codex` | LLM (Codex, OAuth) | `nanobot provider login openai-codex` |
| `github_copilot` | LLM (GitHub Copilot, OAuth) | `nanobot provider login github-copilot` |

<details>
<summary><b>Proveedor Personalizado (Cualquier API compatible con OpenAI)</b></summary>

Se conecta directamente a cualquier endpoint compatible con OpenAI — LM Studio, llama.cpp, Together AI, Fireworks, Azure OpenAI, o cualquier servidor auto-hospedado.

```json
{
  "providers": {
    "custom": {
      "apiKey": "tu-api-key",
      "apiBase": "https://api.tu-proveedor.com/v1"
    }
  },
  "agents": {
    "defaults": {
      "model": "nombre-de-tu-modelo"
    }
  }
}
```

> Para servidores locales que no requieren key, configura `apiKey` como cualquier string no vacío (ej. `"no-key"`).

</details>

<details>
<summary><b>Ollama (local)</b></summary>

Ejecuta un modelo local con Ollama:

**1. Iniciar Ollama** (ejemplo):
```bash
ollama run llama3.2
```

**2. Agregar a config**:
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

</details>

### Configuración de Canales

Configuración global que aplica a todos los canales:

```json
{
  "channels": {
    "sendProgress": true,
    "sendToolHints": false,
    "sendMaxRetries": 3,
    "telegram": { ... }
  }
}
```

| Configuración | Por defecto | Descripción |
|---------------|-------------|-------------|
| `sendProgress` | `true` | Transmitir el progreso del texto del agente al canal |
| `sendToolHints` | `false` | Transmitir hints de llamadas a herramientas (ej. `read_file("…")`) |
| `sendMaxRetries` | `3` | Máximo de intentos de entrega por mensaje saliente |

### Búsqueda Web

> [!TIP]
> Usa `proxy` en `tools.web` para enrutar todas las solicitudes web a través de un proxy:
> ```json
> { "tools": { "web": { "proxy": "http://127.0.0.1:7890" } } }
> ```

nanobot soporta múltiples proveedores de búsqueda web:

| Proveedor | Campos de config | Gratuito |
|-----------|-----------------|----------|
| `brave` (por defecto) | `apiKey` | No |
| `tavily` | `apiKey` | No |
| `jina` | `apiKey` | Nivel gratuito (10M tokens) |
| `searxng` | `baseUrl` | Sí (auto-hospedado) |
| `duckduckgo` | — | Sí |

Cuando faltan credenciales, nanobot automáticamente usa DuckDuckGo.

**DuckDuckGo** (sin configuración):
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

### MCP (Model Context Protocol)

> [!TIP]
> El formato de configuración es compatible con Claude Desktop / Cursor. Puedes copiar las configuraciones de servidores MCP directamente de cualquier README de servidor MCP.

nanobot soporta [MCP](https://modelcontextprotocol.io/) — conecta servidores de herramientas externos y úsalos como herramientas nativas del agente.

```json
{
  "tools": {
    "mcpServers": {
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/ruta/al/dir"]
      },
      "mi-mcp-remoto": {
        "url": "https://ejemplo.com/mcp/",
        "headers": {
          "Authorization": "Bearer xxxxx"
        }
      }
    }
  }
}
```

Dos modos de transporte soportados:

| Modo | Config | Ejemplo |
|------|--------|---------|
| **Stdio** | `command` + `args` | Proceso local vía `npx` / `uvx` |
| **HTTP** | `url` + `headers` (opcional) | Endpoint remoto |

Las herramientas MCP se descubren y registran automáticamente al iniciar. El LLM puede usarlas junto con las herramientas integradas — sin configuración adicional.

### Seguridad

> [!TIP]
> Para despliegues en producción, configura `"restrictToWorkspace": true` en tu config para aislar al agente.
> Desde `v0.1.4.post4`, un `allowFrom` vacío deniega todo acceso por defecto. Para permitir a todos los remitentes, configura `"allowFrom": ["*"]`.

| Opción | Por defecto | Descripción |
|--------|-------------|-------------|
| `tools.restrictToWorkspace` | `false` | Restringe **todas** las herramientas del agente al directorio workspace |
| `tools.exec.enable` | `true` | Habilita/deshabilita la ejecución de comandos shell |
| `channels.*.allowFrom` | `[]` (deniega todo) | Lista blanca de IDs de usuario. Vacío deniega todo; usa `["*"]` para permitir a todos |

### Zona Horaria

Por defecto, nanobot usa `UTC`. Si quieres que el agente piense en tu hora local:

```json
{
  "agents": {
    "defaults": {
      "timezone": "America/Mexico_City"
    }
  }
}
```

Esto afecta las cadenas de tiempo mostradas al modelo, como el contexto de ejecución y los prompts de heartbeat. También se convierte en la zona horaria por defecto para los schedules de cron.

Ejemplos comunes: `UTC`, `America/Mexico_City`, `America/Bogota`, `America/Argentina/Buenos_Aires`, `America/Santiago`, `America/Lima`, `Europe/Madrid`, `America/New_York`, `America/Los_Angeles`, `Europe/London`, `Asia/Tokyo`, `Asia/Shanghai`.

> ¿Necesitas otra zona horaria? Consulta la [Base de Datos de Zonas Horarias IANA](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones) completa.

## 🧩 Múltiples Instancias

Ejecuta múltiples instancias de nanobot simultáneamente con configs y datos de ejecución separados.

### Inicio Rápido

```bash
# Crear configs e instancias separadas
nanobot onboard --config ~/.nanobot-telegram/config.json --workspace ~/.nanobot-telegram/workspace
nanobot onboard --config ~/.nanobot-discord/config.json --workspace ~/.nanobot-discord/workspace
```

Edita cada config con diferentes configuraciones de canal, luego:

```bash
# Instancia A - Bot de Telegram
nanobot gateway --config ~/.nanobot-telegram/config.json

# Instancia B - Bot de Discord
nanobot gateway --config ~/.nanobot-discord/config.json
```

### Notas

- Cada instancia debe usar un puerto diferente si se ejecutan al mismo tiempo
- Usa un workspace diferente por instancia si quieres memoria, sesiones y skills aislados
- Los cron jobs y el estado de ejecución se derivan del directorio de configuración

## 💻 Referencia CLI

| Comando | Descripción |
|---------|-------------|
| `nanobot onboard` | Inicializar config y workspace en `~/.nanobot/` |
| `nanobot onboard --wizard` | Lanzar el asistente de configuración interactivo |
| `nanobot onboard -c <config> -w <workspace>` | Inicializar una instancia específica |
| `nanobot agent -m "..."` | Chatear con el agente |
| `nanobot agent -w <workspace>` | Chatear contra un workspace específico |
| `nanobot agent` | Modo de chat interactivo |
| `nanobot agent --no-markdown` | Mostrar respuestas en texto plano |
| `nanobot agent --logs` | Mostrar logs de ejecución durante el chat |
| `nanobot serve` | Iniciar la API compatible con OpenAI |
| `nanobot gateway` | Iniciar el gateway |
| `nanobot status` | Mostrar estado |
| `nanobot provider login openai-codex` | Login OAuth para proveedores |
| `nanobot channels login <canal>` | Autenticar un canal interactivamente |
| `nanobot channels status` | Mostrar estado de canales |

Salir del modo interactivo: `exit`, `quit`, `/exit`, `/quit`, `:q`, o `Ctrl+D`.

<details>
<summary><b>Heartbeat (Tareas Periódicas)</b></summary>

El gateway se despierta cada 30 minutos y revisa `HEARTBEAT.md` en tu workspace. Si el archivo tiene tareas, el agente las ejecuta y entrega resultados a tu canal de chat más recientemente activo.

**Configurar:** edita `~/.nanobot/workspace/HEARTBEAT.md`:

```markdown
## Tareas Periódicas

- [ ] Revisar pronóstico del clima y enviar resumen
- [ ] Escanear bandeja de entrada en busca de emails urgentes
```

El agente también puede gestionar este archivo él mismo — pídele que "agregue una tarea periódica" y actualizará `HEARTBEAT.md` por ti.

</details>

## 🐍 SDK Python

Usa nanobot como librería — sin CLI, sin gateway, solo Python:

```python
from nanobot import Nanobot

bot = Nanobot.from_config()
result = await bot.run("Resume el README")
print(result.content)
```

Cada llamada lleva un `session_key` para aislamiento de conversación:

```python
await bot.run("hola", session_key="usuario-alice")
await bot.run("hola", session_key="tarea-42")
```

Consulta [docs/PYTHON_SDK.md](PYTHON_SDK.md) para la referencia completa del SDK.

## 🔌 API Compatible con OpenAI

nanobot puede exponer un endpoint mínimo compatible con OpenAI para integraciones locales:

```bash
pip install "nanobot-ai[api]"
nanobot serve
```

Por defecto, la API se vincula a `127.0.0.1:8900`.

### Endpoints

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

### Ejemplo con curl

```bash
curl http://127.0.0.1:8900/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "hola"}],
    "session_id": "mi-sesion"
  }'
```

## 🐳 Docker

```bash
# Construir la imagen
docker build -t nanobot .

# Inicializar config (solo la primera vez)
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot onboard

# Editar config en el host para agregar API keys
vim ~/.nanobot/config.json

# Ejecutar gateway
docker run -v ~/.nanobot:/root/.nanobot -p 18790:18790 nanobot gateway

# O ejecutar un solo comando
docker run -v ~/.nanobot:/root/.nanobot --rm nanobot agent -m "¡Hola!"
```

### Docker Compose

```bash
docker compose run --rm nanobot-cli onboard   # configuración inicial
vim ~/.nanobot/config.json                     # agregar API keys
docker compose up -d nanobot-gateway           # iniciar gateway
```

## 🐧 Servicio Linux

Ejecuta el gateway como servicio de systemd para que se inicie automáticamente y se reinicie en caso de fallo.

**1. Encontrar la ruta del binario:**

```bash
which nanobot   # ej. /home/usuario/.local/bin/nanobot
```

**2. Crear el archivo de servicio** en `~/.config/systemd/user/nanobot-gateway.service`:

```ini
[Unit]
Description=Nanobot Gateway
After=network.target

[Service]
Type=simple
ExecStart=%h/.local/bin/nanobot gateway
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=%h

[Install]
WantedBy=default.target
```

**3. Habilitar e iniciar:**

```bash
systemctl --user daemon-reload
systemctl --user enable --now nanobot-gateway
```

**Operaciones comunes:**

```bash
systemctl --user status nanobot-gateway        # verificar estado
systemctl --user restart nanobot-gateway       # reiniciar después de cambios
journalctl --user -u nanobot-gateway -f        # seguir logs
```

> **Nota:** Los servicios de usuario solo se ejecutan mientras estás logueado. Para mantener el gateway corriendo después de cerrar sesión:
>
> ```bash
> loginctl enable-linger $USER
> ```

## 📁 Estructura del Proyecto

```
nanobot/
├── agent/          # 🧠 Lógica central del agente
│   ├── loop.py     #    Loop del agente (LLM ↔ ejecución de herramientas)
│   ├── context.py  #    Constructor de prompts
│   ├── memory.py   #    Memoria persistente
│   ├── skills.py   #    Cargador de skills
│   ├── subagent.py #    Ejecución de tareas en segundo plano
│   └── tools/      #    Herramientas integradas (incl. spawn)
├── skills/         # 🎯 Skills incluidos (github, weather, tmux...)
├── channels/       # 📱 Integraciones de canales de chat (soporta plugins)
├── bus/            # 🚌 Enrutamiento de mensajes
├── cron/           # ⏰ Tareas programadas
├── heartbeat/      # 💓 Activación proactiva
├── providers/      # 🤖 Proveedores LLM (OpenRouter, etc.)
├── session/        # 💬 Sesiones de conversación
├── config/         # ⚙️ Configuración
└── cli/            # 🖥️ Comandos
```

## 🤝 Contribuir y Roadmap

¡Los PRs son bienvenidos! El código es intencionalmente pequeño y legible. 🤗

### Estrategia de Branches

| Branch | Propósito |
|--------|-----------|
| `main` | Releases estables — correcciones de bugs y mejoras menores |
| `nightly` | Funciones experimentales — nuevas funciones y cambios importantes |

**¿No estás seguro a qué branch apuntar?** Consulta [CONTRIBUTING.md](../CONTRIBUTING.md) para más detalles.

**Roadmap** — ¡Elige un elemento y [abre un PR](https://github.com/HKUDS/nanobot/pulls)!

- [ ] **Multi-modal** — Ver y escuchar (imágenes, voz, video)
- [ ] **Memoria a largo plazo** — Nunca olvidar contexto importante
- [ ] **Mejor razonamiento** — Planificación y reflexión de múltiples pasos
- [ ] **Más integraciones** — Calendario y más
- [ ] **Auto-mejora** — Aprender de retroalimentación y errores

---

<p align="center">
  <sub>nanobot es solo para fines educativos, de investigación e intercambio técnico.</sub>
</p>
