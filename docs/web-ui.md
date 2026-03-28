# nanobot Web UI

The Web UI provides a browser-based interface for configuring and interacting with nanobot, making it easy to use when deployed on platforms like Koyeb.

## Features

- **Dashboard**: Quick overview of system status and quick actions
- **Chat Interface**: Real-time conversation with your AI assistant
- **Configuration**: Manage LLM providers, agent settings, and tools
- **Channel Management**: Configure chat platform integrations (Telegram, Discord, etc.)
- **Status Monitoring**: View detailed system health and configuration status

## Quick Start

### Local Development

1. **Install web dependencies**:
   ```bash
   pip install nanobot-ai[web]
   ```

2. **Start the web UI**:
   ```bash
   nanobot web
   ```

3. **Open your browser**:
   Navigate to http://localhost:18790

### With Authentication

For production deployments, enable authentication:

```bash
# Using command-line argument
nanobot web --auth-token your-secret-token

# Or using environment variable
export NANOBOT_WEB_AUTH_TOKEN=your-secret-token
nanobot web
```

### Custom Port

```bash
nanobot web --port 8080
```

### Custom Config

```bash
nanobot web --config ~/.nanobot-custom/config.json --workspace ~/.nanobot-custom/workspace
```

## Koyeb Deployment

### Option 1: Web UI Mode (Default)

The Dockerfile now defaults to web UI mode. Deploy as usual:

```bash
# Set environment variables in Koyeb
koyeb service update nanobot-gateway \
  --env PORT=18790 \
  --env MODE=web \
  --env NANOBOT_WEB_AUTH_TOKEN=your-secret-token
```

### Option 2: Gateway Mode

If you want to run the gateway instead:

```bash
koyeb service update nanobot-gateway \
  --env PORT=18790 \
  --env MODE=gateway
```

### Option 3: Both Services

Run both web UI and gateway as separate services:

```bash
# Web UI service
koyeb app init nanobot-web \
  --git \
  --git-branch main \
  --git-builder dockerfile \
  --env MODE=web \
  --env PORT=18790 \
  --env NANOBOT_WEB_AUTH_TOKEN=your-secret-token

# Gateway service
koyeb app init nanobot-gateway \
  --git \
  --git-branch main \
  --git-builder dockerfile \
  --env MODE=gateway \
  --env PORT=18790
```

## Web UI Pages

### Dashboard (`/`)

The main dashboard provides:
- System status overview (config, workspace, providers, channels)
- Quick action buttons
- System information
- Quick chat interface for testing

### Chat (`/chat`)

Full-featured chat interface:
- Real-time messaging with the agent
- Markdown rendering for responses
- Session management
- Message history
- Copy responses to clipboard

### Configuration (`/config`)

Manage all nanobot settings:
- **LLM Providers**: Configure API keys for OpenAI, Anthropic, etc.
- **Agent Settings**: Model selection, temperature, max tokens, etc.
- **Gateway Settings**: Port, heartbeat configuration
- **Web Search**: Search provider configuration
- **Tools**: Shell execution, workspace restrictions

### Channels (`/channels`)

Configure chat platform integrations:
- Enable/disable channels
- Configure channel-specific settings
- QR code login for WhatsApp/WeChat (via CLI)

Supported channels:
- Telegram
- Discord
- WhatsApp
- WeChat (Weixin)
- Feishu
- DingTalk
- Slack
- Matrix
- Email
- QQ
- WeCom
- MoChat

### Status (`/status`)

Detailed system monitoring:
- Configuration status
- Workspace status
- Provider configuration
- Channel status
- Tool configuration
- Gateway settings

## API Endpoints

The Web UI exposes several REST API endpoints:

### Health Check

```http
GET /health
```

Response:
```json
{
  "status": "healthy",
  "version": "0.1.4.post5"
}
```

### Configuration

```http
GET /api/config
POST /api/config
```

### Status

```http
GET /api/status
```

### Providers

```http
GET /api/providers
GET /api/models/suggestions?provider=anthropic
```

### Channels

```http
GET /api/channels
```

### Chat

```http
POST /api/chat
Content-Type: application/json
X-Auth-Token: your-token

{
  "message": "Hello!",
  "session_id": "web:default"
}
```

### Authentication

```http
GET /api/auth/check
POST /api/auth/verify
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PORT` | Web UI port | `18790` |
| `MODE` | Run mode: `web` or `gateway` | `web` |
| `NANOBOT_WEB_AUTH_TOKEN` | Authentication token | (none) |
| `NANOBOT_CONFIG` | Custom config path | `~/.nanobot/config.json` |
| `NANOBOT_WORKSPACE` | Custom workspace path | `~/.nanobot/workspace` |

## Security Considerations

### Authentication

- **Always enable authentication in production** using `NANOBOT_WEB_AUTH_TOKEN`
- Without authentication, anyone with URL access can use your nanobot instance
- The token is required for all `/api/*` endpoints

### HTTPS

When deploying behind a reverse proxy or load balancer:
- Terminate HTTPS at the proxy
- Forward requests to the Web UI
- Preserve the `X-Auth-Token` header

Example nginx configuration:
```nginx
server {
    listen 443 ssl;
    server_name nanobot.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:18790;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### CORS

CORS is enabled for API endpoints to allow browser-based access. In production, you may want to restrict this:

Edit `nanobot/web/server.py`:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Auth-Token"],
)
```

## Troubleshooting

### Web UI won't start

1. Check if FastAPI is installed:
   ```bash
   pip install nanobot-ai[web]
   ```

2. Check for port conflicts:
   ```bash
   lsof -i :18790
   ```

3. Check logs for errors:
   ```bash
   nanobot web --debug
   ```

### Authentication issues

1. Verify token is set:
   ```bash
   echo $NANOBOT_WEB_AUTH_TOKEN
   ```

2. Clear browser cache and localStorage
3. Check browser console for 401 errors

### Configuration not saving

1. Check file permissions:
   ```bash
   ls -la ~/.nanobot/config.json
   ```

2. Ensure config file is writable:
   ```bash
   chmod 644 ~/.nanobot/config.json
   ```

3. Check disk space

### Chat not working

1. Verify LLM provider is configured with valid API key
2. Check model name is correct
3. Review agent logs for errors
4. Try a simpler message first

## Development

### Running in Debug Mode

```bash
nanobot web --debug
```

This enables:
- Auto-reload on code changes
- Detailed error pages
- Verbose logging

### File Structure

```
nanobot/
├── web/
│   ├── __init__.py          # Web module
│   ├── server.py            # FastAPI application
│   └── ...
├── templates/
│   └── web/
│       ├── base.html        # Base template
│       ├── index.html       # Dashboard
│       ├── chat.html        # Chat interface
│       ├── config.html      # Configuration
│       ├── channels.html    # Channel management
│       └── status.html      # Status page
└── static/
    ├── css/
    │   └── style.css        # Custom styles
    ├── js/
    │   └── app.js           # Frontend JavaScript
    └── img/
        └── nanobot_logo.png # Logo
```

### Adding New Pages

1. Create HTML template in `nanobot/templates/web/`
2. Add route in `nanobot/web/server.py`
3. Add navigation link in `base.html`

### Adding API Endpoints

1. Add route function in `register_api_routes()` in `server.py`
2. Use `@require_auth` decorator for protected endpoints
3. Update JavaScript API client in `app.js`

## CLI Reference

```bash
# Start web UI
nanobot web

# With custom port
nanobot web --port 8080

# With authentication
nanobot web --auth-token my-secret-token

# With custom config
nanobot web --config ~/.nanobot-custom/config.json

# Debug mode
nanobot web --debug

# Full options
nanobot web --host 0.0.0.0 --port 8080 --config ~/.nanobot/config.json --workspace ~/.nanobot/workspace --auth-token xxx --debug
```

## Migration from CLI

If you're used to using nanobot via CLI:

| CLI Command | Web UI Equivalent |
|-------------|-------------------|
| `nanobot agent -m "..."` | Chat page → Type message |
| `nanobot gateway` | Set `MODE=gateway` |
| Edit `config.json` manually | Configuration page |
| `nanobot status` | Status page |
| `nanobot channels status` | Channels page |

## Support

- **GitHub Issues**: [github.com/HKUDS/nanobot/issues](https://github.com/HKUDS/nanobot/issues)
- **Discord**: [discord.gg/MnCvHqpUGB](https://discord.gg/MnCvHqpUGB)
- **Documentation**: [github.com/HKUDS/nanobot](https://github.com/HKUDS/nanobot)
