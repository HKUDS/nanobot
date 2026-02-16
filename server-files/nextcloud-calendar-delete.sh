#!/bin/bash
# Usage: nextcloud-calendar-delete.sh "EVENT_FILENAME.ics"
# Die Event-Dateinamen stehen in der href-Ausgabe von nextcloud-calendar.sh
EVENT_FILE="$1"
BASE_URL="https://cloud.tillmannheigel.de/remote.php/dav/calendars/tbot777/tbot_shared_by_tillmann/"

if [ -z "$EVENT_FILE" ]; then
  echo "Fehler: Bitte Event-Dateiname angeben (z.B. 279F9746-ED67-46DB-A4BC-BD45A6BFF181.ics)"
  exit 1
fi

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" -u "$NEXTCLOUD_USER:$NEXTCLOUD_PASS" \
  -X DELETE \
  "${BASE_URL}${EVENT_FILE}")

if [ "$RESPONSE" = "204" ]; then
  echo "Termin geloescht: $EVENT_FILE"
else
  echo "Fehler beim Loeschen (HTTP $RESPONSE): $EVENT_FILE"
fi
