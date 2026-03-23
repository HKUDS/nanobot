# Design: Resilient Session Load

**Datum:** 2026-03-23 (v2 — Review R1-R5 konsolidiert)
**Repo:** HKUDS/nanobot
**Branch:** `fix/resilient-session-load`
**Target:** `main` (Bug Fix, keine Verhaltensänderung)

## Problem

`SessionManager._load()` fängt den gesamten Parse-Vorgang in einem einzigen `try/except` ab. Bei JEDEM Exception (korrupte JSONL-Zeile, fehlendes Feld, truncated write) wird `None` zurückgegeben. Der Caller `get_or_create()` erstellt dann eine leere `Session(key=key)` — die komplette Konversations-History ist verloren.

**Auslöser:** Process-Restart während `save()` (open("w") trunciert sofort). Ein incomplete write produziert eine Datei mit einer truncated letzten Zeile → `_load()` crasht → Session leer.

## Review Findings (v2 Änderungen)

Review Runde mit 5 Reviewern (code-review-master, skeptic-coding, skeptic-architecture, skeptic-complexity, code-review-excellence). 12 deduplizierte Findings, alle adressiert:

| # | Severity | Finding | Adresse |
|---|----------|---------|---------|
| 1 | BLOCKER | `parsed_any` + `not metadata` falsch für empty dict | ✅ `recovered` Flag in beiden Branches |
| 2 | BLOCKER | Backup bedingungslos vor Parsing | ✅ Backup komplett gestrichen |
| 3 | BLOCKER | `last_consolidated=0` → Memory-Rekonsolidation | ✅ `_last_consolidated_recovered` sentinel |
| 4 | MAJOR | `shutil.copy2` ohne try/except | ✅ Backup gestrichen |
| 5 | MAJOR | TOCTOU-Race in Backup-Erstellung | ✅ Backup gestrichen |
| 6 | MAJOR | UTF-8 BOM + Encoding-Errors umgehen Recovery | ✅ `encoding="utf-8-sig", errors="replace"` |
| 7 | MAJOR | `save()` Cleanup ohne try/except | ✅ Backup gestrichen |
| 8 | MAJOR | Backup überproportioniert für Bug-Fix PR | ✅ Backup gestrichen |
| 9 | MINOR | Outer `except Exception` zu breit | ✅ `except OSError` |
| 10 | MINOR | Kein Metadata-only Test | ✅ Test hinzugefügt |
| 11 | MINOR | Keine `isinstance(data, dict)` Prüfung | ✅ Hinzugefügt |
| 12 | MINOR | Kein Line-Size-Limit | ✅ `_MAX_LINE_BYTES = 1_000_000` |

**Entscheidung Backup:** Gestrichen. Begründung:
- Per-line Recovery verändert die Originaldatei nicht — sie bleibt auf der Platte, auch wenn korrupt
- Backup war redundant (selbe Daten), erzeugte load↔save Coupling und 40% der Tests
- Beseitigt 5 der 12 Findings auf einen Schlag
- Bei Bedarf: separater PR mit klarem Consumer-Requirement

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: `int()` — bei Parse-Fehler → `0`, aber `_last_consolidated_recovered = True` setzen (siehe §3)
- `metadata`: `dict` — bei Fehler → `{}`

Eine kaputte metadata-line wird mit Warning geloggt aber blockiert nicht den Load.

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except
- Type-Guard: `isinstance(data, dict)` — non-dict Werte werden übersprungen
- Size-Guard: Zeilen > `_MAX_LINE_BYTES` (1MB) werden übersprungen
- Bad line → `logger.warning()` mit Zeilennummer, Session-Key UND Dateipfad
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert (kein Change)
- Encoding: `open(path, encoding="utf-8-sig", errors="replace")` — BOM-tolerant, byte-level Encoding-Fehler isolieren sich auf einzelne Zeilen statt die gesamte Datei zu killen

### 3. Consolidation-Guard für `last_consolidated`

**Problem (BLOCKER R3):** Wenn `last_consolidated` wegen korrupter Metadata auf `0` zurückfällt, re-konsolidiert der MemoryConsolidator ALLE Messages und schreibt doppelte Einträge in MEMORY.md/HISTORY.md — irreversible Korruption.

**Lösung:**
- Neues Feld auf Session: `_last_consolidated_recovered: bool = False`
- Wenn `last_consolidated` auf Default `0` fällt wegen Parse-Fehler → Flag auf `True`
- In `maybe_consolidate_by_tokens`: wenn `session._last_consolidated_recovered` → consolidation skippen mit Warning-Log
- Flag wird nur zurückgesetzt wenn `save()` mit einem vom Disk geladenen `last_consolidated` erfolgreich war

### 4. Rückgabe-Logik

`recovered` Flag wird in BEIDEN Branches gesetzt (metadata UND messages):

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults)` |
| Metadata OK + 0 Messages (auch mit `metadata={}`) | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session, aktuelles Verhalten) |
| Datei existiert nicht | `None` (aktuelles Verhalten) |

### 5. Error-Handling

- Inner per-line: `json.JSONDecodeError` → skip + Warning
- Inner per-field: `ValueError, TypeError` → default + Warning
- Outer: `except OSError` statt `Exception` — I/O-Fehler abfangen, aber keine programmatischen Fehler verschlucken
- Non-dict JSON Werte: `isinstance(data, dict)` Check → skip
- Oversize Lines: `len(stripped) > _MAX_LINE_BYTES` → skip + Warning

## Files

| File | Änderung |
|------|----------|
| `nanobot/session/manager.py` | `_load()` refactor (per-line, encoding, guards), `Session` neues Feld |
| `nanobot/agent/memory.py` | `maybe_consolidate_by_tokens` consolidation-guard |
| `tests/test_session_resilient_load.py` | Neue Testdatei |

## Tests

| Test | Szenario |
|------|----------|
| `test_load_truncated_last_line` | Letzte Zeile truncated JSON → vorherige Messages geladen |
| `test_load_corrupt_middle_line` | Mittlere Zeile invalid JSON → übersprungen, Rest geladen |
| `test_load_all_lines_corrupt_returns_none` | Alle Zeilen invalid → `None` |
| `test_load_completely_empty_file_returns_none` | Leere Datei → `None` |
| `test_load_metadata_only_returns_session` | Nur metadata-line, `metadata={}` → Session (nicht None!) |
| `test_load_corrupt_metadata_created_at` | Invalid created_at → Default, Messages geladen |
| `test_load_corrupt_metadata_last_consolidated` | Invalid last_consolidated → 0, `_last_consolidated_recovered=True` |
| `test_load_metadata_missing_fields` | Nur `_type` in metadata → Defaults |
| `test_load_bom_file` | UTF-8 BOM in Datei → korrekt geladen |
| `test_load_non_dict_line_skipped` | JSON-Zeile ist String statt Dict → übersprungen |
| `test_load_oversize_line_skipped` | Zeile > 1MB → übersprungen |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — behebt die Root Cause, ist aber ein separater PR
- **Backup-Mechanismus** — nur wenn konkreter Consumer-Need identifiziert
- **`list_sessions()` Resilienz** — gleiche Vulnerability, separater Scope
- **`save()` Error-Handling** — Caller-seitiges Problem, separater Scope
