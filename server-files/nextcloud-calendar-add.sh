#!/bin/bash
# Usage: nextcloud-calendar-add.sh "Titel" "2026-02-14T10:00:00" "2026-02-14T11:00:00" "Ort (optional)" "Notizen (optional)"
SUMMARY="$1"
DTSTART="$2"
DTEND="$3"
LOCATION="${4:-}"
DESCRIPTION="${5:-}"

EVENT_UID="$(uuidgen)"
NOW=$(date -u +%Y%m%dT%H%M%SZ)
DTSTART_FMT=$(echo "$DTSTART" | sed 's/[-:]//g')
DTEND_FMT=$(echo "$DTEND" | sed 's/[-:]//g')

ICAL="BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//nanobot//EN
BEGIN:VEVENT
UID:${EVENT_UID}
DTSTAMP:${NOW}
CREATED:${NOW}
LAST-MODIFIED:${NOW}
DTSTART;TZID=Europe/Berlin:${DTSTART_FMT}
DTEND;TZID=Europe/Berlin:${DTEND_FMT}
SUMMARY:${SUMMARY}
LOCATION:${LOCATION}
DESCRIPTION:${DESCRIPTION}
END:VEVENT
END:VCALENDAR"

curl -s -u "$NEXTCLOUD_USER:$NEXTCLOUD_PASS" \
  -X PUT \
  -H "Content-Type: text/calendar" \
  -d "$ICAL" \
  "https://cloud.tillmannheigel.de/remote.php/dav/calendars/tbot777/tbot_shared_by_tillmann/${EVENT_UID}.ics"

echo "Termin erstellt: $SUMMARY ($DTSTART - $DTEND)"
