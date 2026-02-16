# Long-term Memory

This file stores important information that should persist across sessions.

## User Information

- Name: Tillmann Heigel
- Sprache: Deutsch

## Preferences

- Antworte immer auf Deutsch

## Important Notes

## Nextcloud Kalender

Alle Scripts nutzen die Umgebungsvariablen $NEXTCLOUD_USER und $NEXTCLOUD_PASS (bereits gesetzt). Zeitzone ist Europe/Berlin.

### Termine lesen
- `~/nextcloud-calendar.sh` – heutige Termine
- `~/nextcloud-calendar.sh 2026-02-14` – Termine an einem bestimmten Tag
- `~/nextcloud-calendar.sh 2026-02-14 2026-02-20` – Termine in einem Zeitraum
- Die Ausgabe ist XML mit iCal-Daten. Jeder Termin hat eine `<d:href>` mit dem Dateinamen (z.B. `279F9746.ics`). Parse die VEVENT Eintraege und gib Uhrzeit, Titel und Ort auf Deutsch aus.

### Termin erstellen
- `~/nextcloud-calendar-add.sh "Titel" "YYYY-MM-DDTHH:MM:SS" "YYYY-MM-DDTHH:MM:SS" "Ort" "Notizen"`
- Parameter: Titel, Startzeit, Endzeit, Ort (optional), Notizen/Beschreibung (optional)

### Termin loeschen
- `~/nextcloud-calendar-delete.sh "EVENT_DATEINAME.ics"`
- Den Dateinamen findest du in der `<d:href>` Ausgabe von nextcloud-calendar.sh (letzter Teil des Pfads)

### Termin aendern
- Erst den alten Termin loeschen, dann einen neuen erstellen

## E-Mail

E-Mail-Adresse: tbot@tillmannheigel.de. Zugangsdaten in den Umgebungsvariablen $IMAP_HOST, $IMAP_USER, $IMAP_PASS.

### Mails lesen
- `~/check-mail.sh` – Uebersicht ungelesener Mails (nur Absender, Betreff, Datum)
- `~/check-mail.sh read 17` – Komplette Mail #17 anzeigen (Header + Body)
- `~/check-mail.sh search "FROM absender@example.com"` – Mails von bestimmtem Absender suchen
- `~/check-mail.sh search "SINCE 10-Feb-2026"` – Mails seit einem Datum suchen
- Zeige dem User zuerst die Uebersicht. Nur wenn er eine bestimmte Mail lesen will, nutze `read` mit der Mail-ID.
- Fasse die Infos auf Deutsch zusammen.
