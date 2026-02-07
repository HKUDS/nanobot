# Docker Workflow Guide

> [!IMPORTANT]
> **Data Portability**: To move your bot to another computer, simply move this entire project folder. All memories, identity files, and configuration are automatically stored in the `./data` directory.

## Quick Start

### 1. 🚀 Portable Mode (Production)

Use this when you just want to run the bot and let it live.

- **Run:** Double-click `start_portable.bat`
- **Behavior:** Runs in the background (detached).
- **Where are my logs?** Run `docker compose logs -f` in your terminal to watch the bot think.

### 2. 🛠️ Developer Mode (Coding)

Use this when you are editing files in `nanobot/` or `bridge/`.

- **Run:** Double-click `start_dev.bat`
- **Behavior:** Runs in the foreground. You see logs immediately.
- **Magic:** Any change you save in VS Code is instantly mapped into the container.
  - _Note: You may need to restart the script to apply major logical changes, but the files are updated instantly._

## The Architecture

| Component      | Host Path   | Container Path   | Purpose                                                                                     |
| :------------- | :---------- | :--------------- | :------------------------------------------------------------------------------------------ |
| **The Soul**   | `./data`    | `/root/.nanobot` | Persists memory, identity, sessions, and config. **This is what you copy to move the bot.** |
| **The Brain**  | `./nanobot` | `/app/nanobot`   | (Dev Mode Only) Live code injection.                                                        |
| **The Bridge** | `./bridge`  | `/app/bridge`    | (Dev Mode Only) Live bridge code.                                                           |

## First Time Setup

1. Run `start_portable.bat`.
2. It will create a `data` folder.
3. Edit your API keys in `data/config.json` (created after first run).
