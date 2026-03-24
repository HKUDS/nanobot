# Design: Resilient Session Load

**Datum:** 2026-03-24 (v6 — Plan-Review Runde 5 konsolidiert)
**Repo:** HKUDS/nanobot
**Branch:** `fix/resilient-session-load`
**Target:** `main` (Bug Fix, keine Verhaltensänderung für valide Dateien)

## Problem

`SessionManager._load()` fängt den gesamten Parse-Vorgang in einem einzigen `try/except` ab. Bei JEDEM Exception (korrupte JSONL-Zeile, fehlendes Feld, truncated write) wird `None` zurückgegeben. Der Caller `get_or_create()` erstellt dann eine leere `Session(key=key)` — die komplette Konversations-History ist verloren.

**Auslöser:** Process-Restart während `save()` (open("w") trunciert sofort). Ein incomplete write produziert eine Datei mit einer truncated letzten Zeile → `_load()` crasht → Session leer.

## Review History

| Runde | Reviewer | Findings | Decision |
|-------|----------|----------|----------|
| v1 | 5× | 12 (3B, 5M, 4m) | BLOCK |
| v2 | 5× | 20 → 11 dedup (4B, 2M, 5m) | BLOCK |
| v3 | 5× | 18 → 13 dedup (2B, 2M, 9m) | → v4 |
| v4 | 5× | 13 → 12 dedup (1B, 0M, 7m, 2n, 2s) | → v5 |
| v5 | 5× | 7 dedup (0B, 0M, 5m, 2n, 2s) | → v6 |
| v6 | — | — | **PROCEED** |

### v4 → v5 Änderungen (12 Findings adressiert)
- **BLOCKER:** `_make_metadata_line` Default `last_consolidated=0` statt `5` (verhindert ungewolltes Clamping in 6 Tests)
- **BLOCKER:** `test_load_metadata_only_returns_session` Assertion `== 0` statt `== 5`
- **MINOR:** Overflow-Test nutzt `1e999` (JSON float → `inf` → echtes `OverflowError`) statt `10**1000`
- **MINOR:** Non-dict JSON Warning inkl. Dateipfad
- **MINOR:** `total_lines` zählt nur non-empty Zeilen (nach `strip()` Check)
- **MINOR:** Upper-Clamp gestrichen (dead code — alle Consumer handhaben oversized korrekt)
- **MINOR:** Non-dict metadata Warning vor Zuweisung (Lesbarkeit)
- **MINOR:** Happy-Path Roundtrip-Test hinzugefügt (frischer SessionManager)
- **NITPICK:** `updated_at` Verhalten im PR-Description dokumentiert
- **SUGGESTION:** Summary-Log Duplikat-Metadata-Edge-Case als known limitation dokumentiert

### v5 → v6 Änderungen (7 Findings adressiert)
- **MINOR:** PR-Description "Bounds clamping" korrigiert → "Lower-bound clamping" (nur negative Werte)
- **MINOR:** Roundtrip-Test `created_at` Assertion hinzugefügt (End-to-End Verifikation)
- **MINOR:** Index-Shift-Schutz: `or skipped_count > 0` zur Fallback-Condition hinzugefügt (verhindert stilles Verschieben von unconsolidated Messages)
- **MINOR:** `list_sessions()` Encoding-Inkonsistenz als Follow-Up dokumentiert (out-of-scope)
- **MINOR:** Task 5 `--timeout=30` entfernt (pytest-timeout keine Dependency)
- **NITPICK:** Task 1 Baseline-Test-Run hinzugefügt
- **NITPICK:** Task 2 "Expected: FAIL" Text korrigiert (2 Tests würden gegen aktuellen Code schon PASS)
- **SUGGESTION:** Kommentar über outer `except`-Clause hinzugefügt
- **SUGGESTION:** Tasks 5+6 zusammengelegt zu "Verify & validate"

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: Explizite `"last_consolidated" not in data` Prüfung, dann `int()` — bei Fehler oder fehlend → `last_consolidated_untrustworthy = True`
- `metadata`: `isinstance(raw_meta, dict)` Check — non-dict → `{}` + Warning (opportunistische Härtung)

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except (inklusive `RecursionError`)
- Type-Guard: `isinstance(data, dict)` — non-dict Werte werden übersprungen + Warning mit Dateipfad
- Bad line → `logger.warning()` mit Zeilennummer, Session-Key UND Dateipfad
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert
- Encoding: `open(path, encoding="utf-8-sig")` — BOM-tolerant (defensive Maßnahme)

### 3. Consolidation-Sicherheit

**Fallback:** Wenn `last_consolidated` nicht vertrauenswürdig ODER Zeilen übersprungen wurden:

```python
if (last_consolidated_untrustworthy or not metadata_parsed or skipped_count > 0) and messages:
    last_consolidated = len(messages)
```

Der `skipped_count > 0` Check verhindert einen Index-Shift: wenn corrupte Message-Zeilen vor der Consolidation-Grenze liegen, verschieben sich die verbleibenden Messages zu niedrigeren Indizes. Ohne den Check würde `last_consolidated` auf dem alten Wert bleiben und `messages[last_consolidated:]` unconsolidated Messages überspringen. Mit dem Check werden alle geladenen Messages als consolidated betrachtet — sichere Richtung (idempotente Re-Consolidation, kein Datenverlust).

**Bounds-Clamping (nur Lower-Bound):**

```python
if last_consolidated < 0:
    last_consolidated = 0
```

Upper-Bound-Clamp wurde gestrichen (dead code): alle Consumer (`get_history()`, `pick_consolidation_boundary()`, `retain_recent_legal_suffix()`) handhaben `last_consolidated > len(messages)` korrekt via Python-Slice-Semantik (`messages[N:]` → `[]`).

### 4. Summary-Log

Nach dem Parse-Loop, wenn `skipped_count > 0`:

```python
logger.info(
    "Session {} partially recovered: {}/{} lines loaded, {} skipped",
    key, loaded_count, total_lines, skipped_count,
)
```

`total_lines` zählt nur non-empty Zeilen. `loaded_count = len(messages) + (1 if metadata_parsed else 0)`. **Known limitation:** Bei doppelten Metadata-Zeilen stimmt `loaded + skipped != total_lines` (extrem selten, nur bei manuellen Edits oder Double-Writes).

### 5. Error-Handling

- Inner per-line: `json.JSONDecodeError, RecursionError` → skip + Warning
- Inner per-field: `ValueError, TypeError, OverflowError` → default + Warning
- Outer: `except (OSError, UnicodeDecodeError)` — I/O und Encoding
- Non-dict JSON: `isinstance(data, dict)` Check → skip
- Non-dict metadata: `isinstance(raw_meta, dict)` Check → default `{}`

### 6. Rückgabe-Logik

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults, last_consolidated=N)` |
| Metadata OK + 0 Messages | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session) |
| Datei existiert nicht | `None` |

**Known:** `updated_at` wird von `_load()` nicht gelesen — Session nutzt `datetime.now()` als Default. Pre-existing behavior, kein Regression.

## Files

| File | Änderung |
|------|----------|
| `nanobot/session/manager.py` | `_load()` refactor |
| `tests/test_session_resilient_load.py` | Neue Testdatei |

**Keine Änderung an `memory.py`.**

## Tests

| Test | Szenario |
|------|----------|
| `test_load_truncated_last_line` | Letzte Zeile truncated JSON → vorherige Messages geladen |
| `test_load_corrupt_middle_line` | Mittlere Zeile invalid JSON → übersprungen, Rest geladen |
| `test_load_all_lines_corrupt_returns_none` | Alle Zeilen invalid → `None` |
| `test_load_completely_empty_file_returns_none` | Leere Datei → `None` |
| `test_load_non_dict_line_skipped` | JSON-Zeile ist String statt Dict → übersprungen |
| `test_load_bom_file` | UTF-8 BOM in Datei → korrekt geladen |
| `test_load_recursion_error_line_skipped` | Deep-nested JSON → `RecursionError` gefangen |
| `test_load_unicode_decode_error_returns_none` | Mid-Multi-Byte Truncation → `None` |
| `test_load_metadata_only_returns_session` | Nur metadata-line → Session, `last_consolidated=0` |
| `test_load_corrupt_metadata_created_at` | Invalid created_at → Default |
| `test_load_corrupt_metadata_last_consolidated` | Invalid last_consolidated → `len(messages)` |
| `test_load_metadata_missing_fields` | Nur `_type` → Defaults, `last_consolidated=len(messages)` |
| `test_load_corrupt_metadata_json_with_valid_messages` | Metadata-Zeile kaputt + Messages → `len(messages)` |
| `test_load_negative_last_consolidated_clamped` | `last_consolidated=-1` → geclampt auf 0 |
| `test_load_overflow_last_consolidated_clamped` | `last_consolidated=1e999` → `OverflowError` → `len(messages)` |
| `test_load_skipped_line_before_consolidation_boundary` | Corrupte Zeile vor Grenze → `last_consolidated=len(messages)` (Index-Shift Schutz) |
| `test_load_valid_file_roundtrip` | save() → frischer Manager → _load() → alle Felder inkl. `created_at` intakt |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — Root Cause Fix
- **Backup-Mechanismus** — nur bei konkretem Consumer-Need
- **`list_sessions()` Resilienz** — separater Scope; Encoding-Inkonsistenz (`utf-8` vs `utf-8-sig`) in Follow-Up beheben
- **`save()` Error-Handling** — separater Scope
- **`updated_at` Round-Trip** — pre-existing behavior
