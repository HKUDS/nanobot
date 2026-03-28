# Nanobot Configuration Guide

Since `config.json` doesn't support comments, use this guide to fill out your settings. 

The file must be placed at `~/.nanobot/config.json` on node `192.168.22.102`.

### Template Structure

```json
{
  "agents": {
    "defaults": {
      "model": "nvidia/nemotron-3-super-120b-a12b:free",
      "provider": "openrouter"
    }
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "token": "YOUR_TELEGRAM_BOT_TOKEN",
      "allowFrom": [
        "YOUR_TELEGRAM_USER_ID_OR_USERNAME"
      ],
      "proxy": null,
      "replyToMessage": false,
      "groupPolicy": "mention"
    }
  },
  "providers": {
    "openrouter": {
      "apiKey": "YOUR_OPENROUTER_API_KEY"
    }
  }
}
```

### Explanations

| Field | Description |
| :--- | :--- |
| `agents.defaults.model` | The default LLM model name. Set to `"nvidia/nemotron-3-super-120b-a12b:free"` as requested. |
| `agents.defaults.provider` | Overrides auto-detection. Set to `"openrouter"` to route this model correctly through OpenRouter. |
| `channels.telegram.enabled` | Set to `true` to enable Telegram polling channel. |
| `channels.telegram.token` | **REQUIRED**: Insert your Telegram BotFather token here. |
| `channels.telegram.allowFrom` | **Highly Recommended**: List of user IDs or usernames (e.g. `"alexander"`) allowed to talk to the bot on Telegram. Use `*` to allow anyone (not recommended). |
| `channels.telegram.groupPolicy` | `"mention"` (default) means bot only answers if @mentioned. `"open"` triggers for all group messages. |
| `providers.openrouter.apiKey` | **REQUIRED**: Insert your OpenRouter API key here. |

---

### Deployment Steps (via ssh)

The deployment script will copy this repository and run `docker-compose up -d` on `192.168.22.102`.
You can then edit `~/.nanobot/config.json` on that machine to add rewards!
