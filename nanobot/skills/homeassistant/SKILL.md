---
name: homeassistant
description: Control Home Assistant devices and query states via REST API.
homepage: https://developers.home-assistant.io/docs/api/rest
metadata: {"nanobot":{"emoji":"🏠","requires":{"bins":["curl"]}}}
---

# Home Assistant REST API

Control smart home devices through Home Assistant REST API.

## Configuration

The HA instance runs at `http://host.docker.internal:8123` (from within Docker).
Use this token for all requests:
```
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc
```

## Common Operations

### Get all states
```bash
curl -s http://host.docker.internal:8123/api/states \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc"
```

### Get specific entity state
```bash
curl -s http://host.docker.internal:8123/api/states/light.living_room \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc"
```

### Call a service (turn on/off, etc.)
```bash
curl -s -X POST http://host.docker.internal:8123/api/services/light/turn_on \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.living_room"}'
```

### Turn off a device
```bash
curl -s -X POST http://host.docker.internal:8123/api/services/light/turn_off \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.living_room"}'
```

### Toggle a device
```bash
curl -s -X POST http://host.docker.internal:8123/api/services/light/toggle \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.living_room"}'
```

### Set brightness (for lights)
```bash
curl -s -X POST http://host.docker.internal:8123/api/services/light/turn_on \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc" \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "light.living_room", "brightness": 128}'
```

### Get available services
```bash
curl -s http://host.docker.internal:8123/api/services \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJuYW5vYm90X2xvbmdfbGl2ZWRfdG9rZW4iLCJpYXQiOjE3NzI5NzAyODMsImV4cCI6MjA4ODMzMDI4M30.jSl2oclEohBSkuQM8flkca2NoJE0zNuoyKGAqgcKkrc"
```

## Common Entity Domains

- `light.*` - Lights (turn_on, turn_off, toggle)
- `switch.*` - Switches (turn_on, turn_off, toggle)
- `fan.*` - Fans (turn_on, turn_off, toggle, set_percentage)
- `climate.*` - Thermostats (set_temperature, set_hvac_mode)
- `cover.*` - Blinds/Covers (open_cover, close_cover, stop_cover)
- `media_player.*` - Media players (play_media, pause, stop, volume_set)
- `sensor.*` - Read-only sensors (just query state)
- `binary_sensor.*` - On/off sensors (just query state)

## Tips

1. Always query states first to discover available entities
2. Entity IDs follow pattern: `domain.entity_name`
3. Service calls: `/api/services/{domain}/{service}`
4. Use jq to filter JSON: `curl ... | jq '.[] | select(.entity_id | startswith("light."))'`
