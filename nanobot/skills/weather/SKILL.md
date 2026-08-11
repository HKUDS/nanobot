---
name: weather
description: Get current weather and forecasts (no API key required).
homepage: https://wttr.in/:help
metadata: {"nanobot":{"emoji":"🌤️","requires":{"bins":["curl"]}}}
---

# Weather

Two free services, no API keys needed.

## wttr.in (primary)

Choose one request that matches the user's scope. Do not fetch current
conditions separately when a today or forecast request already includes them.

Platform notes:
- On Windows PowerShell, use `curl.exe`; bare `curl` may resolve to
  `Invoke-WebRequest`.
- On macOS and Linux, use `curl`.

Current conditions only:
```bash
curl -s "https://wttr.in/London?format=3"
# Output: London: ⛅️ +8°C
```

Custom current conditions format:
```bash
curl -s "https://wttr.in/London?format=%l:+%c+%t+%h+%w"
# Output: London: ⛅️ +8°C 71% ↙5km/h
```

Today's weather, including current conditions (use this single request for
questions about today's weather):
```bash
curl -s "https://wttr.in/London?1&m"
```

Full forecast:
```bash
curl -s "https://wttr.in/London?T&m"
```

On Windows PowerShell, replace `curl` with `curl.exe` in the commands above.

Format codes: `%c` condition · `%t` temp · `%h` humidity · `%w` wind · `%l` location · `%m` moon

Tips:
- URL-encode spaces: `wttr.in/New+York`
- Airport codes: `wttr.in/JFK`
- Units: `?m` (metric) `?u` (USCS)
- Today only: `?1` · Current only: `?0`
- PNG (macOS/Linux): `curl -s "https://wttr.in/Berlin.png" -o weather.png`
- PNG (Windows PowerShell): `curl.exe -s "https://wttr.in/Berlin.png" -o weather.png`

## Open-Meteo (fallback, JSON)

Free, no key, good for programmatic use:
```bash
curl -s "https://api.open-meteo.com/v1/forecast?latitude=51.5&longitude=-0.12&current_weather=true"
```

Find coordinates for a city, then query. Returns JSON with temp, windspeed, weathercode.

Docs: https://open-meteo.com/en/docs
