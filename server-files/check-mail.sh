#!/bin/bash
# Usage:
#   check-mail.sh                     – Uebersicht ungelesener Mails (Betreff, Absender, Datum)
#   check-mail.sh read 17             – Mail #17 anzeigen (nur Text-Teil mit Links)
#   check-mail.sh search "FROM xyz"   – Mails suchen (IMAP SEARCH Syntax)

ACTION="${1:-list}"

fetch_headers() {
  curl -s "imaps://$IMAP_HOST/INBOX;UID=$1;SECTION=HEADER.FIELDS%20(FROM%20TO%20SUBJECT%20DATE)" -u "$IMAP_USER:$IMAP_PASS" --ssl-reqd 2>/dev/null
}

fetch_body_text() {
  curl -s "imaps://$IMAP_HOST/INBOX;UID=$1" -u "$IMAP_USER:$IMAP_PASS" --ssl-reqd 2>/dev/null \
    | python3 -c "
import sys, email, email.policy
msg = email.message_from_binary_file(sys.stdin.buffer, policy=email.policy.default)
body = msg.get_body(preferencelist=('plain',))
if body:
    print(body.get_content())
else:
    body = msg.get_body(preferencelist=('html',))
    if body:
        import re
        html = body.get_content()
        text = re.sub('<[^>]+>', '', html)
        print(text)
"
}

get_ids() {
  curl -s "imaps://$IMAP_HOST/INBOX" -u "$IMAP_USER:$IMAP_PASS" --ssl-reqd -X "$1" 2>&1 | grep -oE '[0-9]+'
}

case "$ACTION" in
  read)
    MAIL_ID="$2"
    if [ -z "$MAIL_ID" ]; then
      echo "Fehler: Mail-ID angeben, z.B.: check-mail.sh read 17"
      exit 1
    fi
    fetch_headers "$MAIL_ID"
    echo "--- Inhalt ---"
    fetch_body_text "$MAIL_ID"
    ;;
  search)
    IDS=$(get_ids "SEARCH $2")
    if [ -z "$IDS" ]; then
      echo "Keine Mails gefunden."
      exit 0
    fi
    for ID in $IDS; do
      echo "=== Mail #$ID ==="
      fetch_headers "$ID"
      echo ""
    done
    ;;
  *)
    IDS=$(get_ids "SEARCH UNSEEN")
    if [ -z "$IDS" ]; then
      echo "Keine ungelesenen Mails."
      exit 0
    fi
    for ID in $IDS; do
      echo "=== Mail #$ID ==="
      fetch_headers "$ID"
      echo ""
    done
    ;;
esac
