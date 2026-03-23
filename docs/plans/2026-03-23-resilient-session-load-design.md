# Design: Resilient Session Load

**Datum:** 2026-03-23 (v3 — Plan-Review Runde 2 konsolidiert)
**Repo:** HKUDS/nanobot
**Branch:** `fix/resilient-session-load`
**Target:** `main` (Bug Fix, keine Verhaltensänderung)

## Problem

`SessionManager._load()` fängt den gesamten Parse-Vorgang in einem einzigen `try/except` ab. Bei JEDEM Exception (korrupte JSONL-Zeile, fehlendes Feld, truncated write) wird `None` zurückgegeben. Der Caller `get_or_create()` erstellt dann eine leere `Session(key=key)` — die komplette Konversations-History ist verloren.

**Auslöser:** Process-Restart während `save()` (open("w") trunciert sofort). Ein incomplete write produziert eine Datei mit einer truncated letzten Zeile → `_load()` crasht → Session leer.

## Review History

| Runde | Reviewer | Findings | Decision |
|-------|----------|----------|----------|
| v1 | 5× (code-review-master, skeptic-coding, skeptic-architecture, skeptic-complexity, code-review-excellence) | 12 (3B, 5M, 4m) | BLOCK |
| v2 | 5× (gleicher Pool) | 20 → 11 dedupliziert (4B, 2M, 5m) | BLOCK |
| v3 | — | — | PROCEED |

### v1 → v2 Änderungen
- Backup gestrichen (löste 5 Findings)
- `recovered` Flag statt `parsed_any`
- Consolidation-Guard `_last_consolidated_recovered` hinzugefügt
- Encoding `utf-8-sig` + `errors="replace"`
- `except OSError` statt `Exception`
- `isinstance(data, dict)` + `_MAX_LINE_BYTES` Guards

### v2 → v3 Änderungen (11 deduplizierte Findings adressiert)

**Consolidation-Guard komplett ersetzt** — der Sentinel-Ansatz war fundamentally flawed:
- Nicht persistiert → save+restart killt den Flag (#1)
- Nie zurückgesetzt → Consolidation permanent deaktiviert (#2)
- Korrupte Metadata-Zeile → Guard nie gesetzt (#3)
- Test/Code-Mismatch bei fehlendem Feld (#4)
- Overengineered für das Problem (#6)

**Neuer Ansatz:** `last_consolidated = len(messages)` als Fallback. Bedeutet "alle geladenen Messages gelten als konsolidiert." Schlimmster Fall: ein paar Messages werden nicht konsolidiert, korrigiert sich beim nächsten Budget-Trigger. Kein neues Session-Feld, keine memory.py-Änderung, kein Persistenzproblem.

**Weitere Änderungen:**
- `_MAX_LINE_BYTES` gestrichen (chars≠bytes, unrealistisches Szenario, valides JSON würde fälschlich gedroppt)
- `errors="replace"` gestrichen (silent corruption ist schlimmer als klarer Fehler)
- `RecursionError` zum inneren except hinzugefügt (#5)
- `OverflowError` zum `int()` except hinzugefügt (#8)
- metadata-Feld type-validiert (#7)
- Summary-Log nach partieller Recovery (#10)
- Consolidation-Warnung mit Remediation-Hinweis (#11)

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: Explizite `"last_consolidated" not in data` Prüfung, dann `int()` — bei Fehler oder fehlend → `last_consolidated_untrustworthy = True`
- `metadata`: `isinstance(raw_meta, dict)` Check — non-dict → `{}` + Warning

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except (inklusive `RecursionError`)
- Type-Guard: `isinstance(data, dict)` — non-dict Werte werden übersprungen
- Bad line → `logger.warning()` mit Zeilennummer, Session-Key UND Dateipfad
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert
- Encoding: `open(path, encoding="utf-8-sig")` — BOM-tolerant (strict error handling, kein `errors="replace"`)

### 3. Consolidation-Sicherheit ohne Sentinel

**Problem (v2):** `_last_consolidated_recovered` Flag war nicht persistiert, nie zurückgesetzt, und bei komplett korrupter Metadata-Zeile nie gesetzt.

**Lösung (v3):** Nach dem Parse-Loop, wenn `last_consolidated_untrustworthy` und Messages geladen wurden:

```python
if last_consolidated_untrustworthy and messages:
    last_consolidated = len(messages)
    logger.warning(
        "Untrusted last_consolidated in session {} — assuming all {} loaded messages are consolidated",
        key, len(messages),
    )
```

Das bedeutet: "Alle geladenen Messages gelten als bereits konsolidiert." Das ist konservativ und korrekt weil:
- Bei korruptem/fehlendem `last_consolidated` wissen wir nicht wo die Consolidation-Grenze liegt
- `len(messages)` ist der sicherste Annahme (keine Messages werden re-konsolidiert)
- Beim nächsten echten Consolidation-Durchlauf wird `last_consolidated` auf den korrekten Wert gesetzt
- Kein neues Session-Feld, keine memory.py-Änderung, kein Persistenzproblem

### 4. Summary-Log

Nach dem Parse-Loop, wenn `recovered` und `skipped_count > 0`:

```python
if recovered and skipped_count > 0:
    logger.info(
        "Session {} partially recovered: {}/{} lines loaded, {} skipped",
        key, len(messages) + (1 if metadata_parsed else 0), total_lines, skipped_count,
    )
```

### 5. Rückgabe-Logik

`recovered` Flag wird in BEIDEN Branches gesetzt (metadata UND messages):

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults, last_consolidated=N)` |
| Metadata OK + 0 Messages (auch mit `metadata={}`) | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session, aktuelles Verhalten) |
| Datei existiert nicht | `None` (aktuelles Verhalten) |

### 6. Error-Handling

- Inner per-line: `json.JSONDecodeError, RecursionError` → skip + Warning
- Inner per-field: `ValueError, TypeError, OverflowError` → default + Warning
- Outer: `except OSError` — I/O-Fehler abfangen
- Non-dict JSON Werte: `isinstance(data, dict)` Check → skip
- Non-dict metadata: `isinstance(raw_meta, dict)` Check → default `{}`

## Files

| File | Änderung |
|------|----------|
| `nanobot/session/manager.py` | `_load()` refactor (per-line, encoding, guards, summary log) |
| `tests/test_session_resilient_load.py` | Neue Testdatei |

**Keine Änderung an `memory.py`** — keine Cross-Module-Kopplung.

## Tests

| Test | Szenario |
|------|----------|
| `test_load_truncated_last_line` | Letzte Zeile truncated JSON → vorherige Messages geladen |
| `test_load_corrupt_middle_line` | Mittlere Zeile invalid JSON → übersprungen, Rest geladen |
| `test_load_all_lines_corrupt_returns_none` | Alle Zeilen invalid → `None` |
| `test_load_completely_empty_file_returns_none` | Leere Datei → `None` |
| `test_load_non_dict_line_skipped` | JSON-Zeile ist String statt Dict → übersprungen |
| `test_load_bom_file` | UTF-8 BOM in Datei → korrekt geladen |
| `test_load_metadata_only_returns_session` | Nur metadata-line, `metadata={}` → Session (nicht None!) |
| `test_load_corrupt_metadata_created_at` | Invalid created_at → Default, Messages geladen |
| `test_load_corrupt_metadata_last_consolidated` | Invalid last_consolidated → `len(messages)` |
| `test_load_metadata_missing_fields` | Nur `_type` → Defaults, `last_consolidated=len(messages)` |
| `test_load_corrupt_metadata_json_with_valid_messages` | Metadata-Zeile invalid JSON + Messages → geladen, `last_consolidated=len(messages)` |
| `test_load_recursion_error_line_skipped` | Deep-nested JSON → `RecursionError` gefangen, übersprungen |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — behebt die Root Cause, ist aber ein separater PR
- **Backup-Mechanismus** — nur wenn konkreter Consumer-Need identifiziert
- **`list_sessions()` Resilienz** — gleiche Vulnerability, separater Scope
- **`save()` Error-Handling** — Caller-seitiges Problem, separater Scope
