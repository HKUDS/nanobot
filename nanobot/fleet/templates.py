"""File templates dropped into a freshly-initialised agent workspace."""

WORKSPACE_GITIGNORE = """\
# Per-host runtime state — don't ship.
media/
gateway.log
whatsapp-auth/
.nanobot.lock
*.pyc
__pycache__/

# HISTORY.md churns fast; only commit if you really want it.
memory/HISTORY.md
"""
