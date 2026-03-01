# Google Maps Grounding

> **Status: Not implemented**
> **Gemini docs:** https://ai.google.dev/gemini-api/docs/maps-grounding

## What It Is

Integrates Gemini with Google Maps data for accurate, location-aware responses. Accesses 250M+ places worldwide with reviews, photos, addresses, and hours.

## Gemini API Capabilities

### Configuration

```python
tools = [{"googleMaps": {}}]
# Optional: enableWidget, latLng for user location
```

### Data returned

- `groundingChunks` — Maps sources (URI, placeId, title)
- `groundingSupports` — text span → source mappings
- `googleMapsWidgetContextToken` — token for rendering Places widgets

### Features

- Place-specific questions (amenities, hours, etc.)
- Location-based recommendations
- Trip planning and itineraries
- Local guide generation
- Interactive map widgets

### Pricing

$25 per 1,000 grounded prompts; 500 free/day

### Supported models

Gemini 2.5 Pro/Flash/Flash-Lite (NOT Gemini 3)

### Restrictions

Not available in China, Crimea, Cuba, Iran, North Korea, Syria, Vietnam

## Nanobot Implementation

Not implemented. No location-aware features exist.

**Potential use:** location-based recommendations, trip planning, local business queries via chat channels.
