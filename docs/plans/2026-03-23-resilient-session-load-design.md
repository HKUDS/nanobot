# Design: Resilient Session Load

**Datum:** 2026-03-24 (v7 — Plan-Review Runde 6 konsolidiert)
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
| v6 | 5× | 14 dedup (1M, 10m, 2n, 1s) | → v7 |
| v7 | — | — | **PROCEED** |

### v5 → v6 Änderungen (7 Findings adressiert)
- **MINOR:** PR-Description "Bounds clamping" → "Lower-bound clamping"
- **MINOR:** Roundtrip-Test `created_at` Assertion hinzugefügt
- **MINOR:** Index-Shift-Schutz: `or skipped_count > 0` zur Fallback-Condition
- **MINOR:** `list_sessions()` Encoding-Inkonsistenz als Follow-Up dokumentiert
- **MINOR:** Task 5 `--timeout=30` entfernt
- **NITPICK:** Task 1 Baseline-Test-Run hinzugefügt
- **NITPICK:** Task 2 "Expected: FAIL" Text korrigiert
- **SUGGESTION:** Kommentar über outer `except`-Clause
- **SUGGESTION:** Tasks 5+6 zusammengelegt

### v6 → v7 Änderungen (14 Findings adressiert)
- **MAJOR:** `skipped_count > 0` ersetzt durch `skipped_before_boundary` Flag (präziser — triggert nur bei corrupten Zeilen vor der Consolidation-Grenze, vermeidet Over-Consolidation im primären Truncation-Szenario)
- **MAJOR:** Roundtrip-Test erweitert: `last_consolidated > 0` wird über `_load()` verifiziert
- **MINOR:** Design Doc "idempotente Re-Consolidation" korrigiert → "konservative Annahme"
- **MINOR:** Roundtrip-Test nutzt deterministische `datetime` statt Zeitdelta-Assertion
- **MINOR:** Test für after-boundary skip hinzugefügt (verifiziert non-fallback)
- **MINOR:** Test für non-dict metadata field hinzugefügt
- **MINOR:** Test für Datei ohne metadata-line (nur messages) hinzugefügt
- **MINOR:** Skip-Tests assertieren `last_consolidated` (Defense-in-Depth)
- **MINOR:** Unused `datetime` import entfernt
- **MINOR:** Roundtrip Docstring "all fields" korrigiert
- **MINOR:** Warning-Log generalisiert (deckt alle 3 Trigger ab)
- **NITPICK:** Redundanter `SessionManager as SM` Re-Import entfernt
- **NITPICK:** Tasks 2+3 zusammengelegt zu "Write all failing tests"
- **Test count:** 20 (was 17)

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

**Position-aware Index-Shift-Schutz:** Ein `skipped_before_boundary` Flag wird gesetzt, wenn eine corrupte Zeile an einer Position übersprungen wird, die *vor* dem bekannten `last_consolidated`-Wert liegt. Nur dann wird der Fallback ausgelöst:

```python
msg_index = 0
skipped_before_boundary = False

# Im Skip-Branch:
if metadata_parsed and msg_index < last_consolidated:
    skipped_before_boundary = True

# Im Message-Branch:
msg_index += 1

# Nach dem Loop:
if (last_consolidated_untrustworthy or not metadata_parsed or skipped_before_boundary) and messages:
    last_consolidated = len(messages)
```

**Warum `skipped_before_boundary` statt `skipped_count > 0`:**
- Das primäre Truncation-Szenario (corrupte letzte Zeile) platziert die corrupte Zeile *nach* der Consolidation-Grenze. `skipped_count > 0` würde hier den Fallback triggern und die letzten unconsolidated Messages dauerhaft für den LLM unsichtbar machen.
- `skipped_before_boundary` triggert nur bei corrupten Zeilen, die den Index-Shift tatsächlich verursachen (vor der Grenze). Nach-boundary Corruption lässt `last_consolidated` unverändert — die unconsolidated Messages bleiben sichtbar.
- Trade-off: Pre-boundary Corruption (extrem selten, nur bei manuellen Edits oder Diskfehlern) triggert den Fallback → konservative Annahme, dass alle geladenen Messages bereits konsolidiert sind. Consolidation wird verhindert, aber keine Daten gehen verloren.

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

| # | Test | Szenario |
|---|------|----------|
| 1 | `test_load_truncated_last_line` | Letzte Zeile truncated JSON → vorherige Messages geladen |
| 2 | `test_load_corrupt_middle_line` | Mittlere Zeile invalid JSON → übersprungen, Rest geladen |
| 3 | `test_load_all_lines_corrupt_returns_none` | Alle Zeilen invalid → `None` |
| 4 | `test_load_completely_empty_file_returns_none` | Leere Datei → `None` |
| 5 | `test_load_non_dict_line_skipped` | JSON-Zeile ist String statt Dict → übersprungen |
| 6 | `test_load_bom_file` | UTF-8 BOM in Datei → korrekt geladen |
| 7 | `test_load_recursion_error_line_skipped` | Deep-nested JSON → `RecursionError` gefangen |
| 8 | `test_load_unicode_decode_error_returns_none` | Mid-Multi-Byte Truncation → `None` |
| 9 | `test_load_metadata_only_returns_session` | Nur metadata-line → Session, `last_consolidated=0` |
| 10 | `test_load_corrupt_metadata_created_at` | Invalid created_at → Default |
| 11 | `test_load_corrupt_metadata_last_consolidated` | Invalid last_consolidated → `len(messages)` |
| 12 | `test_load_metadata_missing_fields` | Nur `_type` → Defaults, `last_consolidated=len(messages)` |
| 13 | `test_load_corrupt_metadata_json_with_valid_messages` | Metadata-Zeile kaputt + Messages → `len(messages)` |
| 14 | `test_load_negative_last_consolidated_clamped` | `last_consolidated=-1` → geclampt auf 0 |
| 15 | `test_load_overflow_last_consolidated_clamped` | `last_consolidated=1e999` → `OverflowError` → `len(messages)` |
| 16 | `test_load_skipped_line_before_consolidation_boundary` | Corrupte Zeile vor Grenze → `len(messages)` (Index-Shift Schutz) |
| 17 | `test_load_skipped_line_after_consolidation_boundary` | Corrupte Zeile nach Grenze → `last_consolidated` unverändert |
| 18 | `test_load_non_dict_metadata_defaults_to_empty` | metadata Feld ist String statt Dict → `{}` |
| 19 | `test_load_messages_only_no_metadata` | Nur Message-Zeilen, keine metadata-line → `len(messages)` |
| 20 | `test_load_valid_file_roundtrip` | save() → frischer Manager → _load() → alle Felder inkl. `last_consolidated=7` und `created_at` intakt |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — Root Cause Fix
- **Backup-Mechanismus** — nur bei konkretem Consumer-Need
- **`list_sessions()` Resilienz** — separater Scope; Encoding-Inkonsistenz (`utf-8` vs `utf-8-sig`) in Follow-Up beheben
- **`save()` Error-Handling** — separater Scope
- **`updated_at` Round-Trip** — pre-existing behavior
