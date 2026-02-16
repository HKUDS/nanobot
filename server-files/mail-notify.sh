#!/bin/bash
# Prueft auf neue Mails und triggert nanobot ueber den Gateway
# So bleibt der Kontext in der Telegram-Session erhalten

source ~/.nanobot/env.sh

IDS=$(curl -s "imaps://$IMAP_HOST/INBOX" -u "$IMAP_USER:$IMAP_PASS" --ssl-reqd -X "SEARCH UNSEEN" 2>&1 | grep -oE '[0-9]+')

if [ -n "$IDS" ]; then
  COUNT=$(echo "$IDS" | wc -w | tr -d ' ')
  /home/tillmann/.local/bin/nanobot cron add \
    --name "mail-$(date +%s)" \
    --message "Du hast $COUNT neue ungelesene Mail(s). Lies sie mit ~/check-mail.sh und fasse sie mir kurz auf Deutsch zusammen." \
    --at "$(date -u -d '+5 seconds' +%Y-%m-%dT%H:%M:%S)" \
    --channel telegram \
    --to 11550087 \
    --deliver
fi
