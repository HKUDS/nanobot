# Matrix Channel Setup

This document describes how to configure and use the Matrix protocol channel for nanobot.

The Matrix integration allows nanobot to communicate via the Matrix protocol, supporting both direct messages and room-based communication.

## Features

- ✅ Vollständige Matrix-nio Integration mit async/await
- ✅ Unterstützung für Access Token und Password-Authentifizierung
- ✅ Automatisches Joinen bei Raum-Einladungen
- ✅ Konfigurierbare Raum-Richtlinien (open/mention/dm)
- ✅ Sync Token Persistierung (verhindert Replay alter Nachrichten)
- ✅ Markdown zu Matrix HTML Konvertierung
- ✅ Datei-Upload Unterstützung
- ✅ Benutzer-Whitelist (allowFrom)
- ✅ Raum-Whitelist (allowRooms)
- ✅ Bot-Mention Erkennung und Stripping

## Konfiguration

Füge folgende Konfiguration zu deiner nanobot config.toml hinzu:

```toml
[channels.matrix]
enabled = true
homeserver = "https://matrix.example.com"
user_id = "@nanobot:example.com"
access_token = "syt_bmFub2JvdA_..." # Bevorzugte Methode
# password = "fallback_password"    # Alternative

# Optionale Einstellungen
device_id = "NANOBOT"              # Für E2EE
roomPolicy = "mention"             # "mention" | "open" | "dm"
allowFrom = [                      # Benutzer-Whitelist
    "@alice:example.com",
    "@bob:example.com"
]
allowRooms = [                     # Raum-Whitelist (leer = alle)
    "!roomid1:example.com",
    "!roomid2:example.com"
]
e2ee = false                       # End-to-End Verschlüsselung (experimental)
```

## Raum-Richtlinien

### `roomPolicy = "mention"` (Standard)
- In DMs: Antwortet auf alle Nachrichten
- In Räumen: Antwortet nur auf @mentions

### `roomPolicy = "open"`
- Antwortet auf alle Nachrichten in allen Räumen

### `roomPolicy = "dm"`
- Antwortet nur in DMs (Direktnachrichten)

## Access Token erstellen

1. Mit Element Web anmelden
2. **Settings** → **Help & About** → **Advanced**
3. **Access Token** kopieren
4. In der Konfiguration als `access_token` eintragen

**Wichtig**: Bewahre den Access Token sicher auf - er gewährt vollen Zugriff auf den Account.

## Bot Setup

1. Matrix-Account für den Bot erstellen (z.B. `@nanobot:example.com`)
2. Access Token generieren oder Password setzen
3. Konfiguration anpassen
4. nanobot starten

## Auto-Join Verhalten

Der Bot wird automatisch Raum-Einladungen annehmen. Um ihn zu einem Raum hinzuzufügen:

```
/invite @nanobot:example.com
```

## Sync Token

Der Bot speichert den letzten Sync Token in `~/.nanobot/matrix_sync_token`, um alte Nachrichten beim Neustart zu vermeiden.

## Unterstützte Features

### Messaging
- Text-Nachrichten mit Markdown-Formatierung
- Lange Nachrichten werden automatisch aufgeteilt
- HTML-Formatierung für Rich-Text

### Media
- Datei-Uploads (Bilder, Audio, Video, Dokumente)
- Automatische MIME-Type Erkennung
- Unterstützung für verschiedene Dateiformate

### Sicherheit
- Benutzer-basierte Zugriffskontrolle
- Raum-basierte Zugriffskontrolle
- Bot-Mention Erkennung

## Troubleshooting

### "Matrix client not running"
- Prüfe Homeserver-URL und Anmeldedaten
- Überprüfe Netzwerkverbindung zum Homeserver

### "Matrix login failed"
- Prüfe Benutzername und Passwort/Token
- Stelle sicher, dass der Account existiert

### Bot antwortet nicht in Räumen
- Prüfe `roomPolicy` Einstellung
- Bei `mention`: Bot mit `@nanobot` erwähnen
- Prüfe `allowRooms` Whitelist

### Alte Nachrichten beim Neustart
- Sync Token wird in `~/.nanobot/matrix_sync_token` gespeichert
- Bei Problemen die Datei löschen (verursacht einmalig Replay)

## Implementierungsdetails

Der Matrix Channel basiert auf:
- `matrix-nio[e2e]>=0.21.0` für Matrix-Protokoll
- Async/await Architektur wie andere Channels
- BaseChannel Interface für einheitliche Integration
- Vollständige nanobot MessageBus Integration

Entwickelt nach der nanobot Channel-Architektur mit Slack Channel als primäre Referenz.