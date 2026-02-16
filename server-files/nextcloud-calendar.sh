#!/bin/bash
# Usage: nextcloud-calendar.sh [START_DATE] [END_DATE]
# Ohne Parameter: heutige Termine
# Mit Parametern: Termine im Zeitraum (Format: YYYY-MM-DD)
BASE_URL="https://cloud.tillmannheigel.de/remote.php/dav/calendars/tbot777/tbot_shared_by_tillmann/"

if [ -n "$1" ] && [ -n "$2" ]; then
  START=$(date -u -d "$1" +%Y%m%dT000000Z)
  END=$(date -u -d "$2" +%Y%m%dT235959Z)
elif [ -n "$1" ]; then
  START=$(date -u -d "$1" +%Y%m%dT000000Z)
  END=$(date -u -d "$1" +%Y%m%dT235959Z)
else
  START=$(date -u +%Y%m%dT000000Z)
  END=$(date -u +%Y%m%dT235959Z)
fi

curl -s -u "$NEXTCLOUD_USER:$NEXTCLOUD_PASS" \
  -X REPORT \
  -H "Content-Type: application/xml" \
  -H "Depth: 1" \
  -d "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<c:calendar-query xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\">
  <d:prop>
    <d:gettag/>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name=\"VCALENDAR\">
      <c:comp-filter name=\"VEVENT\">
        <c:time-range start=\"${START}\" end=\"${END}\"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>" \
  "$BASE_URL"
