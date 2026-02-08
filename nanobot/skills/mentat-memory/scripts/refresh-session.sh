#!/usr/bin/env bash
# Summarize current session and reset
# Usage: ./scripts/refresh-session.sh

set -e

# Get current session key from gateway
SESSION_KEY=$(clawdbot status --json 2>/dev/null | jq -r '.sessions[0].key // "agent:main:main"')
echo "📊 Summarizing session: $SESSION_KEY"

# Use clawdbot message to trigger the summarization
clawdbot message --text "Pull the current session transcript using sessions_history. Summarize it focusing on: decisions made, work done, insights, and next steps. Append the summary to today's diary file at memory/diary/$(date +%Y)/daily/$(date +%Y-%m-%d).md under '## Sessions' with a timestamp. Update memory/diary/$(date +%Y)/.state.json with the current session key as lastSummarizedSession. Confirm completion."

echo "✅ Summarization requested. Run 'clawdbot new' to start a fresh session when ready."
