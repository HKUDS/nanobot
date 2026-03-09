---
name: asset-manager
description: Use when handling portfolio holdings, broker export xlsx files, workbook-based asset sync, or daily briefing generation for an Asset-Management style project.
metadata: {"nanobot":{"requires":{"bins":["python3"]}}}
---

# Asset Manager

Use this skill for requests about portfolio holdings, asset updates, Excel imports, daily briefings, or Telegram portfolio reports backed by an `Asset-Management` project.

Project-specific absolute paths should live in a workspace override skill. Keep this built-in skill generic.

Read `references/data-contract.md` before non-trivial asset changes.

## Canonical Data Rules

- `assets.xlsx` is the source of truth for holdings.
- `src/data.json` and `public/data.json` are derived outputs.
- Never change holdings, cash, total balance, or symbol quantities by editing JSON directly.
- If the user says a holding changed, update `assets.xlsx` first, then regenerate JSON/report outputs.
- Large position changes require explicit approval before workbook writes.

## Main Workflows

### 1. Broker export import

Use this when the user provides one or more `.xlsx` export files.

```bash
cd <asset-management-root>
python3 scripts/import_positions.py --source "<path1>" --source "<path2>" --keep-symbol GOLD.CN
python3 scripts/asset_pipeline.py run-cycle --time-of-day morning --send-telegram --no-publish --alert-on-failure
```

Notes:
- Keep `GOLD.CN` unchanged unless the user explicitly provides a new gold position.
- If only one source file exists, use one `--source`.
- Require approval if a non-cash position changes by more than 30%, is added, or is removed.
- After import, verify `assets.xlsx` changed on disk before claiming success.

### 2. Refresh existing portfolio

Use this when the user wants latest prices/news/briefing without changing holdings.

```bash
cd <asset-management-root>
python3 scripts/asset_pipeline.py run-cycle --time-of-day morning --send-telegram --no-publish --alert-on-failure
```

### 3. Manual correction without broker export

Use this only when the user gives explicit target values and no import file exists.

Rules:
- Edit `assets.xlsx` only.
- Prefer adjusting the `Holdings` sheet row for the specific symbol.
- Do not remove zero-quantity rows automatically unless the user explicitly asks to clean the sheet.
- After any manual workbook edit, run:

```bash
cd <asset-management-root>
python3 scripts/asset_pipeline.py update-data
python3 scripts/asset_pipeline.py send-briefing --time-of-day morning
```

## Reply Rules

- Do not use markdown pipe tables in Telegram/manual replies.
- Keep replies short and operational.
- Always include:
  - whether `assets.xlsx` changed
  - which symbols changed
  - the latest `last_updated`
  - whether the Telegram briefing was sent
- Flag heavy positions above 30% of non-cash portfolio value.
- Keep zero positions out of holdings summaries and briefings.

Good reply shape:

```text
Portfolio updated.
assets.xlsx changed: yes
Changed symbols: NVDA.US, TSLA.US
last_updated: 2026-03-09 14:30:07
Telegram briefing: sent
```

## Verification

After any holdings update:

1. Check `assets.xlsx` `Holdings` values.
2. Check `src/data.json` `holdings` and `last_updated`.
3. Check heavy-position concentration and zero-quantity filtering in the derived output.
4. If Telegram send was requested, confirm the command succeeded.

Helpful checks:

```bash
cd <asset-management-root>
python3 - <<'PY'
import pandas as pd
df = pd.read_excel('assets.xlsx', sheet_name='Holdings').dropna(how='all')
df.columns = [str(c).strip().lower() for c in df.columns]
print(df[['timestamp', 'symbol', 'quantity']].to_string(index=False))
PY
```

```bash
cd <asset-management-root>
python3 - <<'PY'
import json
with open('src/data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
print(data.get('last_updated'))
print([item.get('symbol') for item in data.get('holdings', [])])
PY
```

## Failure Handling

- If `run-cycle` fails in the advisor step but workbook/JSON updates succeeded, say that clearly.
- If import succeeds but Telegram send fails, report the send failure separately.
- If the user asks for an update and no file path or explicit manual target is available, ask which workbook/export to use instead of guessing.
