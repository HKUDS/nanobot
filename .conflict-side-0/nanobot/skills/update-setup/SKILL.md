---
name: update-setup
description: One-time setup wizard for the nanobot upgrade skill. Triggers: setup update, configure update, 切设置更新, 初始化更新.
---

# Update Setup

Generate a personalized upgrade skill for this workspace.

## Step 1: Check Existing

Use `read_file` to check if `skills/update/SKILL.md` already exists in the workspace.

If it exists, ask the user: "An upgrade skill already exists. Reconfigure?" Wait for the user's reply. If no, stop here.

## Step 2: Current Version and Install Clues

Use `exec` to run `nanobot --version`. Tell the user the current version.

Then collect install clues with `exec`. These commands are best-effort; if one fails,
keep going and show the useful output:

```
command -v nanobot || true
python -m pip show nanobot-ai || true
pipx list | sed -n '/nanobot-ai/,+3p' || true
uv tool list | sed -n '/nanobot-ai/,+3p' || true
```

Summarize what you found in one short paragraph. Use the clues only to suggest a
likely install method. Do not treat them as confirmation.

## Step 3: Confirm Required Inputs

CRITICAL: Do not write `skills/update/SKILL.md` until the install method is
explicitly confirmed by the user. The install method must come from a user
answer or confirmation, not from inference alone. If you cannot get a clear
answer, stop and ask the user to rerun this setup when they know how nanobot was
installed.

Ask the user the questions below, one at a time, in your response text. Wait for
the user's reply before proceeding to the next question. If you cannot get a clear
answer, stop without writing the skill.

**Question 1 — Install method:**

```
question: "I found these install clues: <SUMMARY>. Which update method should this workspace use?"
options: ["uv", "pipx", "pip", "source (git clone)", "not sure"]
```

If the user selected `not sure`, explain the difference between the options and
stop. Do not generate the upgrade skill.

If the user selected `source (git clone)`, ask for the local checkout path:
`question: "Where is your nanobot source checkout? Enter an absolute path or a path relative to this workspace:"`.

**Question 2 — Optional dependencies:**

```
question: "Which optional dependencies do you need? List names separated by spaces, or reply 'none'. Available: api, wecom, weixin, msteams, matrix, discord, langsmith, pdf"
```

Parse the reply. If the user says "none" or similar, set extras to empty. Otherwise collect the valid names.

**Question 3 — Proxy:**

```
question: "Do you need an HTTP proxy to reach PyPI or GitHub?"
options: ["no", "yes"]
```

If yes, ask one more time for the proxy URL: `question: "Enter proxy URL (e.g. http://127.0.0.1:7890):"`.

## Step 4: Generate Skill

Build the extras string. If the user selected dependencies, format as `[dep1,dep2,...]`. Otherwise omit the brackets entirely.

Determine the upgrade command from the install method:

| Method | Command |
|--------|---------|
| uv | `uv tool install "nanobot-ai[EXTRAS]" --force` |
| pipx | `pipx install --force "nanobot-ai[EXTRAS]"` |
| pip | `python -m pip install --upgrade "nanobot-ai[EXTRAS]"` |
| source | `cd <SOURCE_CHECKOUT> && git pull && python -m pip install -e ".[EXTRAS]"` |

For source installs, include extras in the editable install command when selected. Quote the source checkout path if it contains spaces.

Determine the preflight check from the install method:

| Method | Preflight check |
|--------|-----------------|
| uv | `command -v uv` |
| pipx | `command -v pipx` |
| pip | `python -m pip --version` |
| source | `test -d <SOURCE_CHECKOUT> && test -d <SOURCE_CHECKOUT>/.git && test -f <SOURCE_CHECKOUT>/pyproject.toml` |

For source installs, quote the source checkout path in the preflight check if it
contains spaces.

Build the skill content. If proxy is configured, add `export http_proxy=URL` and `export https_proxy=URL` lines before the upgrade command.

Use `write_file` to write `skills/update/SKILL.md` with this content:

```
---
name: update
description: "Upgrade nanobot to the latest version. Triggers: upgrade nanobot, update nanobot, 升级nanobot, 更新nanobot."
---

# Update Nanobot

1. (If proxy configured) Set proxy: `export http_proxy=URL && export https_proxy=URL`
2. Use `exec` to run the preflight check: <PREFLIGHT_CHECK>. If it fails, stop and tell the user to rerun `update-setup` because the saved install method no longer matches this environment.
3. Use `exec` to run the upgrade command: <UPGRADE_COMMAND>
4. Use `exec` to verify: `nanobot --version`
5. Tell the user the new version. Say: "Run `/restart` to restart nanobot and apply the update. If `/restart` is unavailable in this channel, restart the nanobot process manually."
```

## Step 5: Confirm

Tell the user: "Upgrade skill created. Say 'upgrade nanobot' when you want to update."
