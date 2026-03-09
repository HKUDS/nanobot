# Asset-Management Data Contract

## Canonical Ownership

- `assets.xlsx` owns portfolio truth.
- `src/data.json` and `public/data.json` are derived artifacts.
- Holdings changes must start in Excel, not JSON.

## Workbook Sheets

### `Holdings`

Purpose:
- current positions
- broker import target
- source for downstream sync

Important columns:
- `timestamp`
- `account`
- `symbol`
- `name`
- `quantity`
- `price_usd`
- `market_value_usd`

### `Daily`

Purpose:
- derived daily portfolio history

Important columns:
- `date`
- `cash_usd`
- `gold_usd`
- `stocks_usd`
- `total_usd`
- `nav`
- `note`

### `Chart`

Purpose:
- derived plot-ready history

Important columns:
- `date`
- `nav`

### `Exec`

Purpose:
- derived executive snapshot / display surface

Rule:
- do not hand-edit unless explicitly repairing a workbook

## JSON Contract

Typical top-level keys:
- `assets`
- `holdings`
- `chart_data`
- `total_balance`
- `last_updated`
- `performance`
- `insights`
- `advisor_briefing`
- `daily_news`

## Operational Priorities

1. Protect the workbook.
2. Update holdings safely.
3. Regenerate dashboard / chart / daily / holdings outputs automatically.
4. Flag heavy positions above 30% of non-cash portfolio value.
5. Keep zero positions out of derived holdings and briefings.

## Approval Rule

Require explicit user approval before writing the workbook if:
- a non-cash position changes by more than 30%
- a non-cash position is fully removed
- a brand-new non-cash position is added
