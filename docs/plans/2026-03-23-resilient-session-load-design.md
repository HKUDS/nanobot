# Design: Resilient Session Load

**Datum:** 2026-03-24 (v8 — Plan-Review Runde 7 konsolidiert)
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
| v7 | 5× | 12 dedup (1M, 7m, 2n, 2s) | → v8 |
| v8 | — | — | **PROCEED** |

### v7 → v8 Änderungen (12 Findings adressiert)
- **MAJOR:** `skipped_before_boundary` Check aus non-dict Branch entfernt — non-dict JSON Werte waren nie Messages und belegen keinen Message-Slot, verursachen also keinen Index-Shift
- **MINOR:** Known-Limitation-Kommentar für non-standard metadata-Position hinzugefügt
- **MINOR:** `MemoryError` zum inneren per-line except hinzugefügt (defensive Vollständigkeit)
- **MINOR:** `test_load_non_dict_metadata_defaults_to_empty` — `last_consolidated` Assertion hinzugefügt
- **MINOR:** `test_load_corrupt_metadata_json_with_valid_messages` — `metadata == {}` Assertion hinzugefügt
- **MINOR:** Neuer Test `test_load_last_consolidated_exceeds_message_count` — verifiziert dass Upper-Clamp fehlt (lc=10, 5 Messages → lc bleibt 10)
- **MINOR:** Plan-Header Findings-Count korrigiert auf 69 (kumulativ über alle 7 Runden)
- **MINOR:** Empty-File Verhaltensänderung im PR-Body dokumentiert
- **NITPICK:** `test_load_messages_only_no_metadata` — `metadata == {}` Assertion hinzugefügt
- **NITPICK:** `test_load_corrupt_metadata_created_at` — `isinstance(created_at, datetime)` statt `is not None`
- **SUGGESTION:** Neuer Test `test_load_non_dict_line_before_boundary_no_over_consolidation` — verifiziert dass non-dict vor boundary KEINEN Fallback triggert (nach MAJOR-Fix)
- **SUGGESTION:** Summary-Log-Klartext für Duplikat-Metadata-Limitation
- **Test count:** 22 (was 20)

## Lösung

### 1. Metadata robuster parsen

Jedes Feld der metadata-line wird einzeln mit `try/except` umhüllt:

- `created_at`: `datetime.fromisoformat()` — bei Fehler → `None`
- `last_consolidated`: Explizite `"last_consolidated" not in data` Prüfung, dann `int()` — bei Fehler oder fehlend → `last_consolidated_untrustworthy = True`
- `metadata`: `isinstance(raw_meta, dict)` Check — non-dict → `{}` + Warning (opportunistische Härtung)

### 2. Message-Zeilen einzeln parsen

Jede JSONL-Zeile wird separat geparst:

- `json.loads(line)` in eigenem try/except (inklusive `RecursionError`, `MemoryError`)
- Type-Guard: `isinstance(data, dict)` — non-dict Werte werden übersprungen + Warning mit Dateipfad
- Bad line → `logger.warning()` mit Zeilennummer, Session-Key UND Dateipfad
- Zeile wird übersprungen, Rest wird normal geladen
- Leere Zeilen und Whitespace werden weiterhin ignoriert
- Encoding: `open(path, encoding="utf-8-sig")` — BOM-tolerant (defensive Maßnahme)

### 3. Consolidation-Sicherheit

**Position-aware Index-Shift-Schutz:** Ein `skipped_before_boundary` Flag wird gesetzt, wenn eine *korrupte* JSON-Zeile (JSONDecodeError/RecursionError) an einer Position übersprungen wird, die *vor* dem bekannten `last_consolidated`-Wert liegt. Non-dict JSON Werte setzen das Flag **NICHT** — sie waren nie Messages und belegen keinen Message-Slot.

```python
msg_index = 0
skipped_before_boundary = False

# Im JSON-Decode-Error/RecursionError Skip-Branch:
if metadata_parsed and msg_index < last_consolidated:
    skipped_before_boundary = True

# Im Non-Dict Skip-Branch (KEIN skipped_before_boundary Check):
# Non-dict Werte waren nie Messages → kein Index-Shift

# Im Message-Branch:
msg_index += 1

# Nach dem Loop:
if (last_consolidated_untrustworthy or not metadata_parsed or skipped_before_boundary) and messages:
    last_consolidated = len(messages)
```

**Warum non-dict keinen Index-Shift verursacht:** `save()` schreibt nur dicts. Ein non-dict JSON Wert (z.B. `"just a string"`) stammt aus manuellen Edits oder Diskfehlern. Er belegt keine Position im Message-Stream — überspringen verursacht keine Verschiebung der nachfolgenden Messages.

**Known Limitation:** `skipped_before_boundary` wird nur ausgewertet wenn `metadata_parsed=True`. Wenn die metadata-line *nach* den Messages steht (nicht-standard Format, nur bei manuellen Edits), werden pre-metadata Skips nicht erfasst. `save()` schreibt immer metadata zuerst — dieses Szenario ist extrem unwahrscheinlich.

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
    "Session {} partially recovered: {}/{} lines loaded, {} skipped (excludes duplicate metadata)",
    key, loaded_count, total_lines, skipped_count,
)
```

`total_lines` zählt nur non-empty Zeilen. `loaded_count = len(messages) + (1 if metadata_parsed else 0)`. **Known limitation:** Bei doppelten Metadata-Zeilen stimmt `loaded + skipped != total_lines` (extrem selten, nur bei manuellen Edits oder Double-Writes).

### 5. Error-Handling

- Inner per-line: `json.JSONDecodeError, RecursionError, MemoryError` → skip + Warning
- Inner per-field: `ValueError, TypeError, OverflowError` → default + Warning
- Outer: `except (OSError, UnicodeDecodeError)` — I/O und Encoding
- Non-dict JSON: `isinstance(data, dict)` Check → skip (KEIN skipped_before_boundary)
- Non-dict metadata: `isinstance(raw_meta, dict)` Check → default `{}`

### 6. Rückgabe-Logik

| Zustand | Rückgabe |
|---------|----------|
| Metadata OK + N Messages geladen | `Session(messages=N, metadata=...)` |
| Metadata kaputt + N Messages geladen | `Session(messages=N, defaults, last_consolidated=N)` |
| Metadata OK + 0 Messages | `Session(messages=[], metadata=...)` |
| Alles kaputt (nur Errors) | `None` (frische Session) |
| Leere Datei / nur Whitespace | `None` (Verhaltensänderung vs. alt — leerer Session; korrekter da Leerdatei = Datenverlust) |
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
| 18 | `test_load_non_dict_line_before_boundary_no_over_consolidation` | Non-dict vor Grenze → `last_consolidated` unverändert (kein Index-Shift) |
| 19 | `test_load_non_dict_metadata_defaults_to_empty` | metadata Feld ist String statt Dict → `{}` |
| 20 | `test_load_messages_only_no_metadata` | Nur Message-Zeilen, keine metadata-line → `len(messages)` |
| 21 | `test_load_last_consolidated_exceeds_message_count` | lc=10, nur 5 Messages → lc bleibt 10 (kein Upper-Clamp) |
| 22 | `test_load_valid_file_roundtrip` | save() → frischer Manager → _load() → alle Felder inkl. `last_consolidated=7` und `created_at` intakt |

## Ausgespart (Folge-PRs)

- **Atomic Save** (write-to-tmp + os.replace) — Root Cause Fix
- **Backup-Mechanismus** — nur bei konkretem Consumer-Need
- **`list_sessions()` Resilienz** — separater Scope; Encoding-Inkonsistenz (`utf-8` vs `utf-8-sig`) in Follow-Up beheben
- **`save()` Error-Handling** — separater Scope
- **`updated_at` Round-Trip** — pre-existing behavior
