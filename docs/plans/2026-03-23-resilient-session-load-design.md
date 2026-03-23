# Design: Resilient Session Load

**Datum:** 2026-03-23
**Repo:** HKUDS/nanobot
**Branch:** `fix/resilient-session-load`
**Target:** `main` (Bug Fix, keine Verhaltensänderung)

## Problem

`SessionManager._load()` fängt den gesamten Parse-Vorgang in einem einzigen `try/except` ab. Bei JEDEM Exception (korrupte JSONL-Zeile, fehlendes Feld, truncated write) wird `None` zurückgegeben. Der Caller `get_or_create()` erstellt dann eine leere `Session(key=key)` — die komplette Konversations-History ist verloren.

**Auslöser:** Process-Restart während `save()` (open("w") trunciert sofort). Ein incomplete write produziert eine Datei mit einer truncated letzten Zeile → `_load()` crasht → Session leer.

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: `int()` — bei Fehler → `0`
- `metadata`: `dict` — bei Fehler → `{}`

Eine kaputte metadata-line wird mit Warning geloggt aber blockiert nicht den Load.

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except
- Bad line → `logger.warning()` mit Zeilennummer und Session-Key
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert (kein Change)

### 3. Backup vor Recovery

Vor dem resilienten Load-Versuch:

- Prüfen ob `path.jsonl.corrupt` bereits existiert (idempotent — kein Überschreiben)
- Wenn nicht: `shutil.copy2(path, path.with_suffix(".jsonl.corrupt"))`
- `logger.info()` über Backup-Erstellung

### 4. Cleanup bei save()

Nach erfolgreichem Write in `save()`:

- Prüfen ob `path.jsonl.corrupt` existiert
- Wenn ja: löschen mit `path.with_suffix(".jsonl.corrupt").unlink(missing_ok=True)`
- Kein extra Log (normaler Operation-Flow)

### 5. Rückgabe-Logik

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults)` |
| Metadata OK + 0 Messages | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session, aktuelles Verhalten) |
| Datei existiert nicht | `None` (aktuelles Verhalten) |

Schlüsselentscheidung: Wenn mindestens die metadata-line ODER mind. 1 Message erfolgreich geparst werden konnte, wird eine Session zurückgegeben. Nur wenn absolut nichts lesbar ist, wird `None` zurückgegeben.

## Files

| File | Änderung |
|------|----------|
| `nanobot/session/manager.py` | `_load()` refactor, `save()` cleanup-Logik |
| `tests/test_session_resilient_load.py` | Neue Testdatei |

## Tests

| Test | Szenario |
|------|----------|
| `test_load_truncated_last_line` | Letzte Zeile ist truncated JSON → alle vorherigen Messages geladen |
| `test_load_corrupt_middle_line` | Mittlere Zeile ist invalid JSON → Zeile übersprungen, Rest geladen |
| `test_load_corrupt_metadata_created_at` | metadata-line hat invalid created_at → Default, Messages geladen |
| `test_load_corrupt_metadata_last_consolidated` | metadata-line hat invalid last_consolidated → 0, Messages geladen |
| `test_load_completely_empty_file` | Leere Datei → `None` |
| `test_load_all_lines_corrupt` | Alle Zeilen invalid → `None` |
| `test_load_backup_created_on_corrupt` | Korrupte Datei → `.jsonl.corrupt` Backup existiert |
| `test_save_cleans_up_corrupt_backup` | Nach `save()` ist `.jsonl.corrupt` weg |
| `test_load_backup_idempotent` | Zweiter Load mit korrupter Datei → kein Überschreiben des Backups |
| `test_load_metadata_missing_fields` | metadata-line hat nur `_type` → Defaults für alle Felder |
