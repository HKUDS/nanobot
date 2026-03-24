# Design: Resilient Session Load

**Datum:** 2026-03-23 (v4 — Plan-Review Runde 3 konsolidiert)
**Repo:** HKUDS/nanobot
**Branch:** `fix/resilient-session-load`
**Target:** `main` (Bug Fix, keine Verhaltensänderung für valide Dateien)

## Problem

`SessionManager._load()` fängt den gesamten Parse-Vorgang in einem einzigen `try/except` ab. Bei JEDEM Exception (korrupte JSONL-Zeile, fehlendes Feld, truncated write) wird `None` zurückgegeben. Der Caller `get_or_create()` erstellt dann eine leere `Session(key=key)` — die komplette Konversations-History ist verloren.

**Auslöser:** Process-Restart während `save()` (open("w") trunciert sofort). Ein incomplete write produziert eine Datei mit einer truncated letzten Zeile → `_load()` crasht → Session leer.

## Review History

| Runde | Reviewer | Findings | Decision |
|-------|----------|----------|----------|
| v1 | 5× (code-review-master, skeptic-coding, skeptic-architecture, skeptic-complexity, code-review-excellence) | 12 (3B, 5M, 4m) | BLOCK |
| v2 | 5× (gleicher Pool) | 20 → 11 dedupliziert (4B, 2M, 5m) | BLOCK |
| v3 | 5× (gleicher Pool) | 18 → 13 dedupliziert (2B, 2M, 9m) | → v4 |
| v4 | — | — | PROCEED |

### v1 → v2 Änderungen
- Backup gestrichen (löste 5 Findings)
- `recovered` Flag statt `parsed_any`
- Consolidation-Guard `_last_consolidated_recovered` hinzugefügt
- Encoding `utf-8-sig` + `errors="replace"`
- `except OSError` statt `Exception`
- `isinstance(data, dict)` + `_MAX_LINE_BYTES` Guards

### v2 → v3 Änderungen (11 Findings adressiert)
- Consolidation-Guard ersetzt durch `last_consolidated = len(messages)` Fallback
- `_MAX_LINE_BYTES` gestrichen
- `errors='replace'` gestrichen
- `RecursionError` + `OverflowError` in except-Blöcke
- `metadata_parsed` Tracking
- metadata `isinstance` Check
- Summary-Log

### v3 → v4 Änderungen (13 Findings adressiert)
- **BLOCKER 1:** `metadata_parsed` wird jetzt im Fallback-Condition genutzt: `(last_consolidated_untrustworthy or not metadata_parsed) and messages`
- **BLOCKER 2:** `except (OSError, UnicodeDecodeError)` — fängt auch Truncation mid-Multi-Byte
- **MAJOR 1:** Negative `last_consolidated` wird auf 0 geclampt
- **MAJOR 2:** `last_consolidated > len(messages)` wird auf `len(messages)` geclampt (deckt auch Index-Shift-Szenario)
- **MINOR:** Summary-Log Formel und Condition synchronisiert
- **MINOR:** `utf-8-sig` als defensive Maßnahme dokumentiert (kein evidenz-basierter Fix)
- **MINOR:** `isinstance(raw_meta, dict)` als opportunistische Härtung dokumentiert
- **MINOR:** Under-Consolidation Warning erweitert: "(some may not have been summarized)"
- **MINOR:** Self-Correction Claim präzisiert: "self-corrects on next consolidation run if budget is exceeded"
- **MINOR:** OverflowError + UnicodeDecodeError Tests hinzugefügt

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: Explizite `"last_consolidated" not in data` Prüfung, dann `int()` — bei Fehler oder fehlend → `last_consolidated_untrustworthy = True`
- `metadata`: `isinstance(raw_meta, dict)` Check — non-dict → `{}` + Warning (opportunistische Härtung, nicht Teil des Truncation-Fix)

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except (inklusive `RecursionError`)
- Type-Guard: `isinstance(data, dict)` — non-dict Werte werden übersprungen
- Bad line → `logger.warning()` mit Zeilennummer, Session-Key UND Dateipfad
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert
- Encoding: `open(path, encoding="utf-8-sig")` — BOM-tolerant (defensive Maßnahme für Windows-edited Files; `save()` schreibt nie BOM)

### 3. Consolidation-Sicherheit

**Fallback:** Wenn `last_consolidated` nicht vertrauenswürdig (korrupt, fehlend, oder Metadata-Zeile komplett kaputt):

```python
if (last_consolidated_untrustworthy or not metadata_parsed) and messages:
    last_consolidated = len(messages)
```

Bedeutet: "Alle geladenen Messages gelten als bereits konsolidiert." Konservative Annahme die Duplikate in MEMORY.md/HISTORY.md verhindert. Trade-off: einige Messages die eigentlich noch nicht konsolidiert waren werden übersprungen — diese sind aber weiterhin in der JSONL-Datei und im LLM-Context.

**Bounds-Clamping:** Für den Fall dass Metadata geparst wurde aber Werte außerhalb des gültigen Bereichs liegen:

```python
if last_consolidated < 0:
    last_consolidated = 0
elif last_consolidated > len(messages):
    last_consolidated = len(messages)
```

Dies deckt auch das Index-Shift-Szenario ab (corrupte Lines vor der Consolidation-Grenze verschieben die Indizes). Schlimmster Fall: eine Nachricht die eigentlich unconsolidated war wird als consolidated behandelt — aber die History ist nie leer.

### 4. Summary-Log

Nach dem Parse-Loop, wenn `skipped_count > 0`:

```python
logger.info(
    "Session {} partially recovered: {}/{} lines loaded, {} skipped",
    key, len(messages) + (1 if metadata_parsed else 0), total_lines, skipped_count,
)
```

### 5. Error-Handling

- Inner per-line: `json.JSONDecodeError, RecursionError` → skip + Warning
- Inner per-field: `ValueError, TypeError, OverflowError` → default + Warning
- Outer: `except (OSError, UnicodeDecodeError)` — I/O-Fehler und Encoding-Fehler abfangen, aber keine programmatischen Fehler verschlucken
- Non-dict JSON Werte: `isinstance(data, dict)` Check → skip
- Non-dict metadata: `isinstance(raw_meta, dict)` Check → default `{}`

### 6. Rückgabe-Logik

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults, last_consolidated=N)` |
| Metadata OK + 0 Messages (auch mit `metadata={}`) | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session, aktuelles Verhalten) |
| Datei existiert nicht | `None` (aktuelles Verhalten) |

## Files

| File | Änderung |
|------|----------|
| `nanobot/session/manager.py` | `_load()` refactor (per-line, encoding, guards, clamping, summary log) |
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
| `test_load_recursion_error_line_skipped` | Deep-nested JSON → `RecursionError` gefangen, übersprungen |
| `test_load_unicode_decode_error_returns_none` | Mid-Multi-Byte Truncation → `None` statt Crash |
| `test_load_metadata_only_returns_session` | Nur metadata-line, `metadata={}` → Session (nicht None!) |
| `test_load_corrupt_metadata_created_at` | Invalid created_at → Default, Messages geladen |
| `test_load_corrupt_metadata_last_consolidated` | Invalid last_consolidated → `len(messages)` |
| `test_load_metadata_missing_fields` | Nur `_type` → Defaults, `last_consolidated=len(messages)` |
| `test_load_corrupt_metadata_json_with_valid_messages` | Metadata-Zeile invalid JSON + Messages → `last_consolidated=len(messages)` |
| `test_load_negative_last_consolidated_clamped` | `last_consolidated=-1` → geclampt auf 0 |
| `test_load_overflow_last_consolidated_clamped` | `last_consolidated=1e999` → OverflowError → `len(messages)` |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — behebt die Root Cause, ist aber ein separater PR
- **Backup-Mechanismus** — nur wenn konkreter Consumer-Need identifiziert
- **`list_sessions()` Resilienz** — gleiche Vulnerability, separater Scope
- **`save()` Error-Handling** — Caller-seitiges Problem, separater Scope
