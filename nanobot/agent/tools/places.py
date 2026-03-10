"""Google Places API tools for location-based search."""

import os
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool

PLACES_API_BASE = "https://places.googleapis.com/v1/places"


class PlacesSearchTool(Tool):
    """Search for nearby places using Google Places API."""

    name = "places_search"
    description = (
        "Search for places near a location. Use this to find restaurants, cafes, "
        "shops, attractions, etc. Returns names, addresses, ratings, and reviews."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (e.g., 'italian restaurants', 'coffee shops', 'pharmacies')"
            },
            "latitude": {
                "type": "number",
                "description": "Latitude of the search center"
            },
            "longitude": {
                "type": "number",
                "description": "Longitude of the search center"
            },
            "radius": {
                "type": "integer",
                "description": "Search radius in meters (default: 1000, max: 50000)",
                "minimum": 1,
                "maximum": 50000
            },
            "count": {
                "type": "integer",
                "description": "Number of results (1-10)",
                "minimum": 1,
                "maximum": 10
            }
        },
        "required": ["query", "latitude", "longitude"]
    }

    def __init__(self, api_key: str | None = None, max_results: int = 5):
        self._init_api_key = api_key
        self.max_results = max_results

    @property
    def api_key(self) -> str:
        """Resolve API key at call time."""
        return self._init_api_key or os.environ.get("GOOGLE_PLACES_API_KEY", "")

    async def execute(
        self,
        query: str,
        latitude: float,
        longitude: float,
        radius: int = 1000,
        count: int | None = None,
        **kwargs: Any
    ) -> str:
        if not self.api_key:
            return (
                "Error: Google Places API key not configured. Set it in "
                "~/.nanobot/config.json under tools.web.places.apiKey "
                "(or export GOOGLE_PLACES_API_KEY), then restart the gateway."
            )

        n = min(max(count or self.max_results, 1), 10)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # Use the new Places API (v1)
                response = await client.post(
                    f"{PLACES_API_BASE}:searchText",
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": self.api_key,
                        "X-Goog-FieldMask": (
                            "places.displayName,places.formattedAddress,"
                            "places.rating,places.userRatingCount,"
                            "places.priceLevel,places.currentOpeningHours,"
                            "places.reviews,places.websiteUri,places.googleMapsUri"
                        )
                    },
                    json={
                        "textQuery": query,
                        "locationBias": {
                            "circle": {
                                "center": {
                                    "latitude": latitude,
                                    "longitude": longitude
                                },
                                "radius": float(radius)
                            }
                        },
                        "maxResultCount": n
                    }
                )
                response.raise_for_status()
                data = response.json()

            places = data.get("places", [])
            if not places:
                return f"No places found for '{query}' near ({latitude}, {longitude})"

            lines = [f"Found {len(places)} places for '{query}':\n"]

            for i, place in enumerate(places, 1):
                name = place.get("displayName", {}).get("text", "Unknown")
                address = place.get("formattedAddress", "No address")
                rating = place.get("rating")
                rating_count = place.get("userRatingCount", 0)
                price = place.get("priceLevel", "")
                maps_url = place.get("googleMapsUri", "")

                # Format rating
                rating_str = f"{rating}/5 ({rating_count} reviews)" if rating else "No ratings"

                # Format price level
                price_str = ""
                if price:
                    price_map = {
                        "PRICE_LEVEL_FREE": "Free",
                        "PRICE_LEVEL_INEXPENSIVE": "$",
                        "PRICE_LEVEL_MODERATE": "$$",
                        "PRICE_LEVEL_EXPENSIVE": "$$$",
                        "PRICE_LEVEL_VERY_EXPENSIVE": "$$$$"
                    }
                    price_str = f" | {price_map.get(price, price)}"

                # Opening hours
                hours = place.get("currentOpeningHours", {})
                open_now = hours.get("openNow")
                hours_str = ""
                if open_now is not None:
                    hours_str = " | Open now" if open_now else " | Closed"

                lines.append(f"{i}. {name}")
                lines.append(f"   {address}")
                lines.append(f"   {rating_str}{price_str}{hours_str}")
                if maps_url:
                    lines.append(f"   Maps: {maps_url}")

                # Include top review if available
                reviews = place.get("reviews", [])
                if reviews:
                    review = reviews[0]
                    review_text = review.get("text", {}).get("text", "")
                    if review_text:
                        # Truncate long reviews
                        if len(review_text) > 150:
                            review_text = review_text[:150] + "..."
                        lines.append(f"   Review: \"{review_text}\"")

                lines.append("")  # Empty line between places

            return "\n".join(lines)

        except httpx.HTTPStatusError as e:
            logger.error("Places API HTTP error: {} - {}", e.response.status_code, e.response.text)
            return f"Error: Places API request failed ({e.response.status_code})"
        except Exception as e:
            logger.error("Places search error: {}", e)
            return f"Error: {e}"
