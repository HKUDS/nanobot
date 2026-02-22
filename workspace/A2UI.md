# A2UI — Agent-to-UI Response Format

You can optionally return structured JSON to render rich Discord UI (Components V2).

## Response Formats

### Plain Text
Just respond with normal Markdown text.

### Simple JSON (buttons + images)
```
{"markdown":"Your message text","ui_intent":{"buttons":[{"label":"Retry","style":"primary","action":"rerun"}]},"images":["https://example.com/img.png"]}
```

### A2UI (stateful UI surfaces)
```
{"a2ui":[{"type":"createSurface","surfaceId":"main","components":[...]}]}
```

## A2UI Envelope Types

| Type | Purpose |
|------|---------|
| `createSurface` | Create a new UI surface with `components` and optional `dataModel` |
| `updateComponents` | Replace components on an existing surface |
| `updateDataModel` | Replace the data model (re-renders template with new data) |
| `deleteSurface` | Remove a surface message |

## Component Types

- **text** — Static text: `{"type":"text","markdown":"# Hello"}`
- **button** — Interactive button: `{"type":"button","label":"Click","style":"primary","action":"do_thing"}`
- **select** — Dropdown menu: `{"type":"select","action":"pick","options":[{"label":"A","value":"a"}]}`
- **section** — Layout with text + accessory (button/thumbnail): `{"type":"section","components":[...],"accessory":{...}}`
- **container** — Grouping container: `{"type":"container","components":[...]}`
- **separator** — Visual divider: `{"type":"separator"}`
- **thumbnail** — Thumbnail image: `{"type":"thumbnail","url":"https://..."}`
- **media_gallery** — Image gallery: `{"type":"media_gallery","items":[{"url":"https://..."}]}`

## Button Styles
`primary` | `secondary` | `success` | `danger` | `link`
- `link` style requires `url` field and has no callback
- Other styles use `action` field for callbacks

## Data Model Templates
Use `{{path.to.value}}` syntax in text components. The data model is bound when rendering:
```
{"type":"createSurface","surfaceId":"main","dataModel":{"name":"Alice","score":42},"components":[{"type":"text","markdown":"Hello {{name}}! Score: {{score}}"}]}
```

## Rules
- Do NOT wrap JSON in markdown code fences
- Do NOT use markdown tables in Discord (use bullet lists instead)
- Max 3 buttons per reply
- Max 4 images per reply
- Apply envelopes in array order
- `updateDataModel` is full replacement, not merge
