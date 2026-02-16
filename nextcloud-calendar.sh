#!/bin/bash
TODAY_START=$(date -u +%Y%m%dT000000Z)
TODAY_END=$(date -u +%Y%m%dT235959Z)

curl -s -u "$NEXTCLOUD_USER:$NEXTCLOUD_PASS" \
  -X REPORT \
  -H "Content-Type: application/xml" \
  -H "Depth: 1" \
  -d "<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<c:calendar-query xmlns:d=\"DAV:\" xmlns:c=\"urn:ietf:params:xml:ns:caldav\">
  <d:prop>
    <c:calendar-data/>
  </d:prop>
  <c:filter>
    <c:comp-filter name=\"VCALENDAR\">
      <c:comp-filter name=\"VEVENT\">
        <c:time-range start=\"${TODAY_START}\" end=\"${TODAY_END}\"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>" \
  "https://cloud.tillmannheigel.de/remote.php/dav/calendars/tbot777/tbot_shared_by_tillmann/"
