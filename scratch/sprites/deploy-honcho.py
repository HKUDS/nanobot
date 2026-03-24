# /// script
# requires-python = ">=3.10"
# ///
"""Deploy nanobot-honcho (honcho-default branch) to a Fly Sprite.

Honcho is a required dependency and enabled by default on this branch.

Usage:
    uv run scratch/sprites/deploy-honcho.py
"""

import json
import os
import shutil
import subprocess
import sys
from getpass import getpass

SPRITE_NAME = "nb-honcho"
REPO = "https://github.com/plastic-labs/nanobot-honcho.git"
BRANCH = "honcho-default"
WORKSPACE_ID = "nanobot-test-honcho"
NANOBOT_BIN = ""

PROVIDERS = [
    ("openrouter",  "OPENROUTER_API_KEY",  "anthropic/claude-sonnet-4-5",      "gateway -- any model",  "https://openrouter.ai/keys"),
    ("anthropic",   "ANTHROPIC_API_KEY",   "anthropic/claude-sonnet-4-5",      "Claude models",         "https://console.anthropic.com"),
    ("openai",      "OPENAI_API_KEY",      "openai/gpt-4o",                    "GPT models",            "https://platform.openai.com/api-keys"),
    ("deepseek",    "DEEPSEEK_API_KEY",    "deepseek/deepseek-chat",           "DeepSeek models",       "https://platform.deepseek.com"),
    ("gemini",      "GEMINI_API_KEY",      "gemini/gemini-2.0-flash",          "Google Gemini",         "https://aistudio.google.com/apikey"),
    ("groq",        "GROQ_API_KEY",        "groq/llama-3.3-70b-versatile",    "fast inference",        "https://console.groq.com/keys"),
]

PROVIDER = {}


def run(cmd, check=True, capture=False, **kw):
    return subprocess.run(cmd, check=check, capture_output=capture, text=True, **kw)

def sprite(*args, check=True):
    return run(["sprite", *args], check=check)

def sprite_exec(script, check=True):
    return sprite("exec", "bash", "-c", script, check=check)

def info(msg): print(f"\033[1m>> {msg}\033[0m")
def ok(msg): print(f"   \033[32m{msg}\033[0m")
def warn(msg): print(f"   \033[33m{msg}\033[0m")
def fail(msg): print(f"   \033[31m{msg}\033[0m"); sys.exit(1)
def dim(msg): print(f"   \033[2m{msg}\033[0m")

def ensure_var(name, prompt, help_text=""):
    val = os.environ.get(name, "")
    if val:
        dim(f"{name} set from environment")
        return val
    if help_text: dim(help_text)
    val = input(f"   {prompt}: ").strip()
    if not val: fail("Value required")
    os.environ[name] = val
    return val

def ensure_sprite_cli():
    info("Checking sprite CLI")
    if shutil.which("sprite"):
        r = run(["sprite", "version"], capture=True, check=False)
        ok(f"found ({r.stdout.strip()})" if r.returncode == 0 else "found")
        return
    warn("sprite CLI not found -- installing")
    run(["sh", "-c", "curl -fsSL https://sprites.dev/install.sh | sh"])
    if not shutil.which("sprite"):
        os.environ["PATH"] = f"{os.path.expanduser('~/.local/bin')}:{os.environ['PATH']}"
    if not shutil.which("sprite"):
        fail("sprite CLI install failed. See https://sprites.dev")
    ok("installed")

def ensure_sprite_login():
    info("Checking sprite auth")
    r = sprite("list", check=False)
    if r.returncode == 0:
        ok("authenticated")
        return
    warn("Not logged in")
    input("   Press Enter to open browser for auth...")
    sprite("login")
    if sprite("list", check=False).returncode != 0:
        fail("sprite login failed")
    ok("authenticated")

def choose_provider():
    info("Provider")
    for i, (name, _env, _model, desc, url) in enumerate(PROVIDERS, 1):
        print(f"   {i}. {name:<14} {desc:<24} {url}")
    choice = input("   Select provider [1]: ").strip() or "1"
    try:
        idx = int(choice) - 1
        if not (0 <= idx < len(PROVIDERS)):
            raise ValueError
    except ValueError:
        fail(f"Invalid choice: {choice}")
    name, env, default_model, desc, url = PROVIDERS[idx]
    PROVIDER["name"] = name
    PROVIDER["env"] = env
    PROVIDER["default_model"] = default_model
    PROVIDER["url"] = url
    ok(f"{name}")

def choose_model():
    info("Model")
    default = PROVIDER["default_model"]
    dim(f"default: {default}")
    choice = input(f"   Model [{default}]: ").strip()
    PROVIDER["model"] = choice if choice else default
    ok(PROVIDER["model"])

def collect_keys():
    info("API keys")
    key = ensure_var(PROVIDER["env"], f"{PROVIDER['name']} API key", PROVIDER["url"])
    PROVIDER["key"] = key
    ensure_var("TELEGRAM_BOT_TOKEN", "Telegram bot token", "@BotFather on Telegram -> /newbot")
    ensure_var("HONCHO_API_KEY", "Honcho API key", "https://app.honcho.dev")

def create_sprite():
    info(f"Creating sprite: {SPRITE_NAME}")
    r = sprite("create", SPRITE_NAME, "-skip-console", check=False)
    ok("created" if r.returncode == 0 else "already exists")
    sprite("use", SPRITE_NAME)

def clone_repo():
    info(f"Cloning {REPO} @ {BRANCH}")
    sprite_exec(f"rm -rf /home/sprite/nanobot && git clone --branch {BRANCH} --single-branch --depth 1 {REPO} /home/sprite/nanobot")
    ok("cloned")

def install_uv():
    info("Installing uv on sprite")
    r = sprite_exec("command -v uv >/dev/null 2>&1 || ~/.local/bin/uv --version >/dev/null 2>&1", check=False)
    if r.returncode == 0:
        ok("already installed")
        return
    sprite_exec("curl -LsSf https://astral.sh/uv/install.sh | sh")
    ok("installed")

def install_nanobot():
    global NANOBOT_BIN
    info("Installing nanobot")
    sprite_exec("export PATH=$HOME/.local/bin:$PATH && cd /home/sprite/nanobot && uv pip install --system --no-cache -e .")
    r = run(["sprite", "exec", "bash", "-c",
             "export PATH=$HOME/.local/bin:$PATH && python3 -c \"import shutil; print(shutil.which('nanobot'))\""],
            capture=True, check=False)
    NANOBOT_BIN = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ""
    if not NANOBOT_BIN:
        r2 = run(["sprite", "exec", "bash", "-c",
                  "find /.sprite/languages -name nanobot -type f 2>/dev/null | head -1"],
                 capture=True, check=False)
        NANOBOT_BIN = r2.stdout.strip() if r2.returncode == 0 else "nanobot"
    ok(f"installed ({NANOBOT_BIN})")

def write_config():
    info("Writing config")
    config = {
        "providers": {PROVIDER["name"]: {"apiKey": PROVIDER["key"]}},
        "agents": {"defaults": {"model": PROVIDER["model"]}},
        "channels": {"telegram": {"enabled": True, "token": os.environ["TELEGRAM_BOT_TOKEN"], "allowFrom": []}},
        "honcho": {"enabled": True, "workspaceId": WORKSPACE_ID, "prefetch": True},
        "tools": {"exec": {"timeout": 60}},
    }
    config_json = json.dumps(config, indent=2)
    sprite_exec("mkdir -p /home/sprite/.nanobot/workspace")
    sprite_exec(f"cat > /home/sprite/.nanobot/config.json << 'ENDJSON'\n{config_json}\nENDJSON")
    sprite_exec(f"echo 'HONCHO_API_KEY={os.environ['HONCHO_API_KEY']}' > /home/sprite/.nanobot/.env")
    ok(f"config.json + .env written ({PROVIDER['name']}/{PROVIDER['model']})")

def onboard():
    info("Running onboard")
    sprite_exec(f"export HOME=/home/sprite && {NANOBOT_BIN} onboard 2>/dev/null || true")
    ok("done")

def register_service():
    info("Registering nanobot service")
    startup = f"#!/bin/bash\nset -a\nsource /home/sprite/.nanobot/.env\nset +a\nexport HOME=/home/sprite\nexec {NANOBOT_BIN} gateway --port 8080\n"
    sprite_exec(f"cat > /home/sprite/start-nanobot.sh << 'STARTSH'\n{startup}STARTSH\nchmod +x /home/sprite/start-nanobot.sh")
    sprite("exec", "sprite-env", "services", "create", "nanobot",
           "--cmd", "bash", "--args", "/home/sprite/start-nanobot.sh", check=False)
    sprite("exec", "sprite-env", "services", "start", "nanobot", check=False)
    sprite("url", "update", "--auth", "public", check=False)
    ok("service started")

def summary():
    r = run(["sprite", "url"], capture=True, check=False)
    url = r.stdout.strip() if r.returncode == 0 else "unknown"
    print()
    print(f"\033[1m== {SPRITE_NAME} deployed ==\033[0m")
    print(f"   Branch:    {BRANCH}")
    print(f"   Honcho:    required dep, enabled by default")
    print(f"   Workspace: {WORKSPACE_ID}")
    print(f"   URL:       {url}")
    print()
    print(f"   Status:    sprite exec -s {SPRITE_NAME} nanobot status")
    print(f"   Logs:      sprite exec -s {SPRITE_NAME} bash -c 'cat /.sprite/logs/services/nanobot.log'")
    print(f"   Console:   sprite console -s {SPRITE_NAME}")

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--provider", help="Provider name (openrouter, anthropic, openai, deepseek, gemini, groq)")
    p.add_argument("--provider-key", help="API key for the chosen provider")
    p.add_argument("--model", help="Model identifier (e.g. anthropic/claude-sonnet-4-5)")
    p.add_argument("--telegram-token"); p.add_argument("--honcho-key")
    args = p.parse_args()

    if args.provider:
        match = [p for p in PROVIDERS if p[0] == args.provider]
        if not match: fail(f"Unknown provider: {args.provider}")
        name, env, default_model, desc, url = match[0]
        PROVIDER.update({"name": name, "env": env, "default_model": default_model, "url": url})
        if args.provider_key: os.environ[env] = args.provider_key; PROVIDER["key"] = args.provider_key
        PROVIDER["model"] = args.model or default_model
    if args.telegram_token: os.environ["TELEGRAM_BOT_TOKEN"] = args.telegram_token
    if args.honcho_key: os.environ["HONCHO_API_KEY"] = args.honcho_key

    ensure_sprite_cli()
    ensure_sprite_login()

    if not PROVIDER.get("name"):
        choose_provider()
        choose_model()
    collect_keys()
    create_sprite()
    clone_repo()
    install_uv()
    install_nanobot()
    write_config()
    onboard()
    register_service()
    summary()
