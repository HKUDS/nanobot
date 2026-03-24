# /// script
# requires-python = ">=3.10"
# ///
"""Deploy vanilla HKUDS/nanobot + auto-apply Honcho skill to a Fly Sprite.

Clones upstream nanobot (no Honcho code), then patches in Honcho support
by copying reference files and modifying source. Every step is traced to a log.

Usage:
    uv run scratch/deploy-vanilla.py
    uv run scratch/deploy-vanilla.py --openrouter-key sk-or-... --telegram-token 123:ABC --honcho-key hch-...
"""

import json
import os
import shutil
import subprocess
import sys
from getpass import getpass

SPRITE_NAME = "nb-vanilla"
VANILLA_REPO = "https://github.com/HKUDS/nanobot.git"
VANILLA_BRANCH = "main"
SKILL_REPO = "https://github.com/plastic-labs/nanobot-honcho.git"
SKILL_BRANCH = "honcho-default"
WORKSPACE_ID = "nanobot-test-vanilla"
TRACE_LOG = "/home/sprite/skill-apply-trace.log"
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(cmd: list[str], check: bool = True, capture: bool = False, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=check, capture_output=capture, text=True, **kw)


def sprite(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return run(["sprite", *args], check=check)


def sprite_exec(script: str, check: bool = True) -> subprocess.CompletedProcess:
    return sprite("exec", "bash", "-c", script, check=check)


def info(msg: str):
    print(f"\033[1m>> {msg}\033[0m")


def ok(msg: str):
    print(f"   \033[32m{msg}\033[0m")


def warn(msg: str):
    print(f"   \033[33m{msg}\033[0m")


def fail(msg: str):
    print(f"   \033[31m{msg}\033[0m")
    sys.exit(1)


def dim(msg: str):
    print(f"   \033[2m{msg}\033[0m")


def ask(prompt: str, help_text: str = "", secret: bool = False) -> str:
    if help_text:
        dim(help_text)
    fn = getpass if secret else input
    value = fn(f"   {prompt}: ").strip()
    if not value:
        fail(f"Value required")
    return value


def ensure_var(name: str, prompt: str, help_text: str = "", secret: bool = False) -> str:
    val = os.environ.get(name, "")
    if val:
        dim(f"{name} set from environment")
        return val
    val = ask(prompt, help_text, secret)
    os.environ[name] = val
    return val


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

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
    dim("This will open your browser for authentication.")
    input("   Press Enter to continue...")
    sprite("login")
    r = sprite("list", check=False)
    if r.returncode != 0:
        fail("sprite login failed. Try: sprite login")
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


# ---------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------

def create_sprite():
    info(f"Creating sprite: {SPRITE_NAME}")
    r = sprite("create", SPRITE_NAME, "-skip-console", check=False)
    ok("created" if r.returncode == 0 else "already exists")
    sprite("use", SPRITE_NAME)


def clone_repos():
    info(f"Cloning vanilla nanobot ({VANILLA_REPO} @ {VANILLA_BRANCH})")
    sprite_exec(f"""
        rm -rf /home/sprite/nanobot /home/sprite/skill-source
        git clone --branch {VANILLA_BRANCH} --single-branch --depth 1 {VANILLA_REPO} /home/sprite/nanobot
    """)
    ok("cloned vanilla")

    info(f"Cloning skill source ({SKILL_REPO} @ {SKILL_BRANCH})")
    sprite_exec(f"""
        git clone --branch {SKILL_BRANCH} --single-branch --depth 1 {SKILL_REPO} /home/sprite/skill-source
    """)
    ok("cloned skill source")


def apply_skill():
    """Patch Honcho support into vanilla nanobot via inline Python on the sprite."""
    info("Applying Honcho skill to vanilla nanobot (with trace logging)")

    # The entire patching logic runs as a single Python script on the sprite
    patch_script = r'''
import os, json, time, subprocess

NANOBOT = '/home/sprite/nanobot'
SKILL   = '/home/sprite/skill-source'
LOG     = '''' + TRACE_LOG + r''''

def log(msg):
    ts = time.strftime('%H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with open(LOG, 'a') as f:
        f.write(line + '\n')

def log_file(path, label):
    log(f'{label}: {path}')
    try:
        with open(path) as f:
            content = f.read()
        log(f'  size: {len(content)} bytes, {content.count(chr(10))} lines')
    except Exception as e:
        log(f'  ERROR reading: {e}')

log('=== Honcho skill auto-apply started ===')

# step 1: create honcho package
honcho_pkg = os.path.join(NANOBOT, 'nanobot', 'honcho')
os.makedirs(honcho_pkg, exist_ok=True)
init_path = os.path.join(honcho_pkg, '__init__.py')
with open(init_path, 'w') as f:
    f.write('"""Honcho integration for AI-native memory.\n\n'
            'This package is only active when honcho.enabled=true in config and\n'
            'HONCHO_API_KEY is set. All honcho-ai imports are deferred to avoid\n'
            'ImportError when the package is not installed.\n'
            '"""\n')
log_file(init_path, 'Created __init__.py')

# step 2: copy reference files
copies = [
    ('nanobot/skills/honcho/references/client.py',     'nanobot/honcho/client.py'),
    ('nanobot/skills/honcho/references/session.py',     'nanobot/honcho/session.py'),
    ('nanobot/skills/honcho/references/honcho_tool.py', 'nanobot/agent/tools/honcho.py'),
]
for src_rel, dst_rel in copies:
    src = os.path.join(SKILL, src_rel)
    dst = os.path.join(NANOBOT, dst_rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src) as f:
        content = f.read()
    with open(dst, 'w') as f:
        f.write(content)
    log_file(dst, f'Copied {src_rel}')

# step 3: patch pyproject.toml
log('--- Patching pyproject.toml ---')
pp_path = os.path.join(NANOBOT, 'pyproject.toml')
with open(pp_path) as f:
    pp = f.read()

if 'honcho' not in pp:
    idx = pp.find('[project.optional-dependencies]')
    if idx == -1:
        log('  ERROR: [project.optional-dependencies] not found')
    else:
        idx_dev = pp.find('dev = [', idx)
        idx_close = pp.find(']', idx_dev) if idx_dev != -1 else -1
        if idx_close == -1:
            log('  ERROR: could not find dev array end')
        else:
            pt = idx_close + 1
            while pt < len(pp) and pp[pt] != '\n':
                pt += 1
            pt += 1
            inj = 'honcho = ["honcho-ai>=2.0.1"]\n'
            pp = pp[:pt] + inj + pp[pt:]
            with open(pp_path, 'w') as f:
                f.write(pp)
            log(f'  Injected: {inj.strip()}')
else:
    log('  Already has honcho, skipping')

# step 4: patch schema.py
log('--- Patching schema.py ---')
sp = os.path.join(NANOBOT, 'nanobot', 'config', 'schema.py')
with open(sp) as f:
    s = f.read()

hc_class = '\nclass HonchoConfig(BaseModel):\n    """Honcho AI-native memory integration."""\n    enabled: bool = False\n    workspace_id: str = "nanobot"\n    prefetch: bool = True\n    context_tokens: int | None = None\n    environment: str = "production"\n\n\n'

if 'HonchoConfig' not in s:
    m = 'class Config(BaseSettings):'
    i = s.find(m)
    if i == -1:
        log('  ERROR: Config class not found')
    else:
        s = s[:i] + hc_class + s[i:]
        log('  Injected HonchoConfig class')

    m2 = 'tools: ToolsConfig = Field(default_factory=ToolsConfig)'
    i2 = s.find(m2)
    if i2 == -1:
        log('  ERROR: tools field not found')
    else:
        eol = s.find('\n', i2)
        inj = '\n    honcho: HonchoConfig = Field(default_factory=HonchoConfig)'
        s = s[:eol] + inj + s[eol:]
        log('  Injected honcho field')

    with open(sp, 'w') as f:
        f.write(s)

# step 5: patch loop.py
log('--- Patching loop.py ---')
lp = os.path.join(NANOBOT, 'nanobot', 'agent', 'loop.py')
with open(lp) as f:
    l = f.read()

if 'honcho_config' not in l:
    m = 'session_manager: SessionManager | None = None,'
    i = l.find(m)
    if i != -1:
        e = i + len(m)
        l = l[:e] + '\n        honcho_config: "HonchoConfig | None" = None,' + l[e:]
        log('  Injected honcho_config param')

    m2 = 'self.restrict_to_workspace = restrict_to_workspace'
    i2 = l.find(m2)
    if i2 != -1:
        e2 = l.find('\n', i2)
        l = l[:e2] + '\n        self.honcho_config = honcho_config' + l[e2:]
        log('  Injected self.honcho_config')

    m3 = 'if self.cron_service:\n            self.tools.register(CronTool(self.cron_service))'
    i3 = l.find(m3)
    if i3 != -1:
        reg = l.find('self.tools.register(CronTool(self.cron_service))', i3)
        e3 = l.find('\n', reg)
        hb = '''

        # Honcho tools (conditional on config + env)
        if self.honcho_config and self.honcho_config.enabled:
            import os as _os
            if _os.environ.get("HONCHO_API_KEY"):
                try:
                    from nanobot.honcho.client import get_honcho_client, HonchoConfig as HClientConfig
                    from nanobot.honcho.session import HonchoSessionManager
                    from nanobot.agent.tools.honcho import HonchoTool

                    _hcfg = HClientConfig(
                        workspace_id=self.honcho_config.workspace_id,
                        api_key=_os.environ["HONCHO_API_KEY"],
                        environment=self.honcho_config.environment,
                    )
                    get_honcho_client(_hcfg)
                    _hsm = HonchoSessionManager(
                        context_tokens=self.honcho_config.context_tokens,
                    )
                    self._honcho_session_manager = _hsm
                    self.tools.register(HonchoTool(session_manager=_hsm))
                    logger.info("Honcho tools registered (query_user_context)")
                except ImportError:
                    logger.warning("Honcho enabled but honcho-ai not installed")
                except Exception as _e:
                    logger.warning(f"Failed to initialize Honcho: {_e}")'''
        l = l[:e3] + hb + l[e3:]
        log('  Injected Honcho tool registration')

    with open(lp, 'w') as f:
        f.write(l)

# step 6: patch commands.py
log('--- Patching commands.py ---')
cp = os.path.join(NANOBOT, 'nanobot', 'cli', 'commands.py')
with open(cp) as f:
    c = f.read()

if 'honcho_config' not in c:
    mk = 'restrict_to_workspace=config.tools.restrict_to_workspace,'
    count = 0
    off = 0
    while True:
        i = c.find(mk, off)
        if i == -1:
            break
        e = i + len(mk)
        inj = '\n        honcho_config=config.honcho,'
        c = c[:e] + inj + c[e:]
        off = e + len(inj) + 1
        count += 1
        log(f'  Injected honcho_config at AgentLoop #{count}')

    with open(cp, 'w') as f:
        f.write(c)

# step 7: git diff
log('--- Capturing git diff ---')
r = subprocess.run(['git', 'diff', '--stat'], cwd=NANOBOT, capture_output=True, text=True)
log(f'git diff --stat:\n{r.stdout}')

r2 = subprocess.run(['git', 'diff'], cwd=NANOBOT, capture_output=True, text=True)
with open(LOG, 'a') as f:
    f.write('\n=== FULL DIFF ===\n')
    f.write(r2.stdout)
    f.write('\n=== END DIFF ===\n')
log(f'Full diff: {len(r2.stdout)} bytes')

log('=== Honcho skill auto-apply completed ===')
'''

    sprite_exec(f"cd /home/sprite && python3 << 'PYEOF'\n{patch_script}\nPYEOF")
    ok("skill applied")


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
    info("Installing nanobot + honcho-ai")
    sprite_exec("""
        export PATH=$HOME/.local/bin:$PATH
        cd /home/sprite/nanobot
        uv pip install --system --no-cache -e '.[honcho]'
    """)
    r = run(["sprite", "exec", "bash", "-c",
             "export PATH=$HOME/.local/bin:$PATH && python3 -c \"import shutil; print(shutil.which('nanobot'))\""],
            capture=True, check=False)
    NANOBOT_BIN = r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else ""
    if not NANOBOT_BIN:
        r2 = run(["sprite", "exec", "bash", "-c",
                  "find /.sprite/languages -name nanobot -type f 2>/dev/null | head -1"],
                 capture=True, check=False)
        NANOBOT_BIN = r2.stdout.strip() if r2.returncode == 0 else ""
    if NANOBOT_BIN:
        ok(f"installed ({NANOBOT_BIN})")
    else:
        warn("installed (could not resolve binary path, using 'nanobot')")
        NANOBOT_BIN = "nanobot"


def write_config():
    info("Writing config (honcho enabled)")
    config = {
        "providers": {PROVIDER["name"]: {"apiKey": PROVIDER["key"]}},
        "agents": {"defaults": {"model": PROVIDER["model"]}},
        "channels": {
            "telegram": {
                "enabled": True,
                "token": os.environ["TELEGRAM_BOT_TOKEN"],
                "allowFrom": [],
            }
        },
        "honcho": {
            "enabled": True,
            "workspaceId": WORKSPACE_ID,
            "prefetch": True,
        },
        "tools": {"exec": {"timeout": 60}},
    }
    config_json = json.dumps(config, indent=2)

    sprite_exec("mkdir -p /home/sprite/.nanobot/workspace")
    sprite_exec(f"cat > /home/sprite/.nanobot/config.json << 'ENDJSON'\n{config_json}\nENDJSON")
    sprite_exec(f"echo 'HONCHO_API_KEY={os.environ['HONCHO_API_KEY']}' > /home/sprite/.nanobot/.env")
    ok(f"config.json + .env written ({PROVIDER['name']}/{PROVIDER['model']})")


def onboard():
    info("Running onboard")
    sprite_exec(f"""
        export HOME=/home/sprite
        {NANOBOT_BIN} onboard 2>/dev/null || true
    """)
    ok("done")


def register_service():
    info("Registering nanobot service")
    startup = f"""#!/bin/bash
set -a
source /home/sprite/.nanobot/.env
set +a
export HOME=/home/sprite
exec {NANOBOT_BIN} gateway --port 8080
"""
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
    print(f"   Source:    vanilla HKUDS/nanobot + Honcho skill auto-applied")
    print(f"   Honcho:    patched in, enabled via config")
    print(f"   Workspace: {WORKSPACE_ID}")
    print(f"   URL:       {url}")
    print()
    print(f"   Status:    sprite exec -s {SPRITE_NAME} nanobot status")
    print(f"   Logs:      sprite exec -s {SPRITE_NAME} sprite-env services logs nanobot")
    print(f"   Trace log: sprite exec -s {SPRITE_NAME} cat {TRACE_LOG}")
    print(f"   Console:   sprite console -s {SPRITE_NAME}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--provider", help="Provider name (openrouter, anthropic, openai, deepseek, gemini, groq)")
    p.add_argument("--provider-key", help="API key for the chosen provider")
    p.add_argument("--model", help="Model identifier (e.g. anthropic/claude-sonnet-4-5)")
    p.add_argument("--telegram-token", help="Telegram bot token")
    p.add_argument("--honcho-key", help="Honcho API key")
    args = p.parse_args()

    if args.provider:
        match = [p for p in PROVIDERS if p[0] == args.provider]
        if not match: fail(f"Unknown provider: {args.provider}")
        name, env, default_model, desc, url = match[0]
        PROVIDER.update({"name": name, "env": env, "default_model": default_model, "url": url})
        if args.provider_key: os.environ[env] = args.provider_key; PROVIDER["key"] = args.provider_key
        PROVIDER["model"] = args.model or default_model
    if args.telegram_token:
        os.environ["TELEGRAM_BOT_TOKEN"] = args.telegram_token
    if args.honcho_key:
        os.environ["HONCHO_API_KEY"] = args.honcho_key

    ensure_sprite_cli()
    ensure_sprite_login()

    if not PROVIDER.get("name"):
        choose_provider()
        choose_model()
    collect_keys()

    create_sprite()
    clone_repos()
    apply_skill()
    install_uv()
    install_nanobot()
    write_config()
    onboard()
    register_service()
    summary()
