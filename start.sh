#!/usr/bin/env bash
# nanobot startup script
# Attiva il venv e avvia nanobot con la config corretta

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
NANOBOT_BIN="$VENV/bin/nanobot"

# Assicurati che il vault Obsidian sia configurato
export NANOBOT_OBSIDIAN_VAULT="/home/ab/Obsidian"

# Controlla che l'API key sia settata
if [[ -z "$ANTHROPIC_API_KEY" ]]; then
    echo "ERRORE: ANTHROPIC_API_KEY non è settata."
    echo "Esporta la variabile prima di avviare nanobot:"
    echo "  export ANTHROPIC_API_KEY='sk-ant-...'"
    exit 1
fi

echo "Avvio nanobot..."
echo "  Vault Obsidian: $NANOBOT_OBSIDIAN_VAULT"
echo "  Workspace:      $HOME/.nanobot"
echo ""

exec "$NANOBOT_BIN" "$@"
