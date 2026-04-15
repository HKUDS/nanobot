# EXTEND.md Schema

Structure for user preferences in `.baoyu-skills/baoyu-slide-deck/EXTEND.md`.

## Full Schema

```yaml
# Slide Deck Preferences

## Defaults
style: blueprint              # Preset name OR "custom"
audience: general             # beginners | intermediate | experts | executives | general
language: auto                # auto | en | zh | ja | etc.
review: true                  # true = review outline before generation

## Custom Dimensions (only when style: custom)
dimensions:
  texture: clean              # clean | grid | organic | pixel | paper
  mood: professional          # professional | warm | cool | vibrant | dark | neutral
  typography: geometric       # geometric | humanist | handwritten | editorial | technical
  density: balanced           # minimal | balanced | dense

## Custom Styles (optional)
custom_styles:
  my-style:
    texture: organic
    mood: warm
    typography: humanist
    density: minimal
    description: "My custom warm and friendly style"
```

## Field Descriptions

### Defaults

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `style` | string | `blueprint` | Preset name, `custom`, or custom style name |
| `audience` | string | `general` | Default target audience |
| `language` | string | `auto` | Output language (auto = detect from input) |
| `review` | boolean | `true` | Show outline review before generation |

### Custom Dimensions

Only used when `style: custom`. Defines dimension values directly.

| Field | Options | Default |
|-------|---------|---------|
| `texture` | clean, grid, organic, pixel, paper | clean |
| `mood` | professional, warm, cool, vibrant, dark, neutral | professional |
| `typography` | geometric, humanist, handwritten, editorial, technical | geometric |
| `density` | minimal, balanced, dense | balanced |

### Custom Styles

Define reusable custom dimension combinations.

```yaml
custom_styles:
  style-name:
    texture: <texture>
    mood: <mood>
    typography: <typography>
    density: <density>
    description: "Optional description"
```

Then use with: `/baoyu-slide-deck content.md --style style-name`

## Minimal Examples

### Just change default style

```yaml
style: sketch-notes
```

### Prefer no reviews

```yaml
review: false
```

### Custom default dimensions

```yaml
style: custom
dimensions:
  texture: organic
  mood: professional
  typography: humanist
  density: minimal
```

### Define reusable custom style

```yaml
custom_styles:
  brand-style:
    texture: clean
    mood: vibrant
    typography: editorial
    density: balanced
    description: "Company brand style"
```

## File Locations

Priority order (first found wins):

1. `.baoyu-skills/baoyu-slide-deck/EXTEND.md` (project)
2. `$HOME/.baoyu-skills/baoyu-slide-deck/EXTEND.md` (user)

## First-Time Setup

When no EXTEND.md exists, the skill prompts for initial preferences:

1. Preferred style (preset or custom)
2. Default audience
3. Language preference
4. Review preference
5. Save location (project or user)

Creates EXTEND.md at chosen location.
