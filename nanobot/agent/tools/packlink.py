"""Packlink Pro shipping tool for nanobot.

Exposes four agent-callable tools:
  packlink_quote  — get available services and prices for a destination
  packlink_ship   — create a shipment (draft → confirmed)
  packlink_label  — get the PDF label URL for a shipment
  packlink_track  — get current status of a shipment
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters

_BASE_URL = "https://api.packlink.com/v1"

# Sender defaults from environment
_SENDER = {
    "name":     lambda: os.environ.get("PACKLINK_SENDER_NAME", ""),
    "surname":  lambda: os.environ.get("PACKLINK_SENDER_SURNAME", ""),
    "street1":  lambda: os.environ.get("PACKLINK_SENDER_STREET", ""),
    "city":     lambda: os.environ.get("PACKLINK_SENDER_CITY", ""),
    "zip_code": lambda: os.environ.get("PACKLINK_SENDER_ZIP", ""),
    "country":  lambda: os.environ.get("PACKLINK_SENDER_COUNTRY", "IT"),
    "phone":    lambda: os.environ.get("PACKLINK_SENDER_PHONE", ""),
    "email":    lambda: os.environ.get("PACKLINK_SENDER_EMAIL", ""),
}


def _api_key() -> str:
    key = os.environ.get("PACKLINK_API_KEY", "")
    if not key:
        raise ValueError("PACKLINK_API_KEY not set")
    return key


def _headers() -> dict:
    return {
        "Authorization": _api_key(),
        "Content-Type": "application/json",
    }


def _sender_defaults() -> dict:
    return {k: v() for k, v in _SENDER.items()}


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "to_country":  {"type": "string", "description": "Destination country code (e.g. IT, DE, FR)"},
        "to_zip":      {"type": "string", "description": "Destination ZIP/postal code"},
        "weight":      {"type": "number", "description": "Package weight in kg (e.g. 0.5)"},
        "width":       {"type": "number", "description": "Package width in cm"},
        "height":      {"type": "number", "description": "Package height in cm"},
        "length":      {"type": "number", "description": "Package length in cm"},
    },
    "required": ["to_country", "to_zip", "weight", "width", "height", "length"],
})
class PacklinkQuoteTool(Tool):
    """Get available shipping services and prices from Packlink Pro."""

    name = "packlink_quote"
    description = (
        "Get available shipping services and prices for a package from the sender's address "
        "to a given destination. Returns carrier name, price, transit time, and service ID."
    )
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(os.environ.get("PACKLINK_API_KEY"))

    @classmethod
    def create(cls, ctx: Any) -> "PacklinkQuoteTool":
        return cls()

    async def execute(
        self,
        to_country: str,
        to_zip: str,
        weight: float,
        width: float,
        height: float,
        length: float,
    ) -> str:
        from_zip = os.environ.get("PACKLINK_SENDER_ZIP", "")
        from_country = os.environ.get("PACKLINK_SENDER_COUNTRY", "IT")

        params = {
            "from[country]": from_country,
            "from[zip]": from_zip,
            "to[country]": to_country.upper(),
            "to[zip]": to_zip,
            "packages[0][weight]": weight,
            "packages[0][width]": width,
            "packages[0][height]": height,
            "packages[0][length]": length,
        }

        async with httpx.AsyncClient(timeout=20) as client:
            resp = client.get(f"{_BASE_URL}/services", headers=_headers(), params=params)
            resp = await client.get(f"{_BASE_URL}/services", headers=_headers(), params=params)
            resp.raise_for_status()
            services = resp.json()

        if not services:
            return f"No shipping services found for {to_country} {to_zip}."

        lines = [f"## Available services → {to_country} {to_zip} | {weight}kg {width}x{height}x{length}cm\n"]
        for s in sorted(services, key=lambda x: float(x.get("base_price", 999))):
            lines.append(
                f"- **{s['carrier_name']} — {s['name']}** | "
                f"€{s['price']['total_price']:.2f} | "
                f"{s.get('transit_time','?')} | "
                f"ID: `{s['id']}`"
                + (" | Drop-off" if s.get("dropoff") else "")
            )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Ship
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "service_id":        {"type": "integer", "description": "Service ID from packlink_quote"},
        "collection_date":   {"type": "string",  "description": "Collection date YYYY/MM/DD"},
        "to_name":           {"type": "string",  "description": "Recipient first name"},
        "to_surname":        {"type": "string",  "description": "Recipient last name"},
        "to_street":         {"type": "string",  "description": "Recipient street and number"},
        "to_city":           {"type": "string",  "description": "Recipient city"},
        "to_zip":            {"type": "string",  "description": "Recipient ZIP code"},
        "to_country":        {"type": "string",  "description": "Recipient country code (e.g. IT)"},
        "to_phone":          {"type": "string",  "description": "Recipient phone number"},
        "to_email":          {"type": "string",  "description": "Recipient email"},
        "weight":            {"type": "number",  "description": "Package weight in kg"},
        "width":             {"type": "number",  "description": "Package width in cm"},
        "height":            {"type": "number",  "description": "Package height in cm"},
        "length":            {"type": "number",  "description": "Package length in cm"},
        "content":           {"type": "string",  "description": "Brief description of contents"},
        "content_value":     {"type": "number",  "description": "Declared value in EUR"},
        "order_reference":   {"type": "string",  "description": "Optional internal order reference"},
    },
    "required": [
        "service_id", "collection_date",
        "to_name", "to_surname", "to_street", "to_city", "to_zip", "to_country", "to_phone",
        "weight", "width", "height", "length", "content", "content_value",
    ],
})
class PacklinkShipTool(Tool):
    """Create a shipment on Packlink Pro."""

    name = "packlink_ship"
    description = (
        "Create a shipment on Packlink Pro. Requires a service_id from packlink_quote "
        "and recipient details. Returns the Packlink reference number."
    )
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(os.environ.get("PACKLINK_API_KEY"))

    @classmethod
    def create(cls, ctx: Any) -> "PacklinkShipTool":
        return cls()

    async def execute(
        self,
        service_id: int,
        collection_date: str,
        to_name: str,
        to_surname: str,
        to_street: str,
        to_city: str,
        to_zip: str,
        to_country: str,
        to_phone: str,
        weight: float,
        width: float,
        height: float,
        length: float,
        content: str,
        content_value: float,
        to_email: str = "",
        order_reference: str = "",
    ) -> str:
        sender = _sender_defaults()

        payload = {
            "service_id": service_id,
            "collection_date": collection_date,
            "from": {
                "name":     sender["name"],
                "surname":  sender["surname"],
                "street1":  sender["street1"],
                "city":     sender["city"],
                "zip_code": sender["zip_code"],
                "country":  sender["country"],
                "phone":    sender["phone"],
                "email":    sender["email"],
            },
            "to": {
                "name":     to_name,
                "surname":  to_surname,
                "street1":  to_street,
                "city":     to_city,
                "zip_code": to_zip,
                "country":  to_country.upper(),
                "phone":    to_phone,
                "email":    to_email,
            },
            "packages": [{
                "weight": weight,
                "width":  width,
                "height": height,
                "length": length,
            }],
            "content":      content,
            "contentvalue": content_value,
        }
        if order_reference:
            payload["shipment_custom_reference"] = order_reference

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{_BASE_URL}/shipments", headers=_headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()

        ref = data.get("reference") or data.get("packlink_reference", "unknown")
        logger.info("Packlink shipment created: {}", ref)

        return (
            f"## Shipment created ✓\n"
            f"- **Reference**: `{ref}`\n"
            f"- **To**: {to_name} {to_surname}, {to_street}, {to_zip} {to_city} ({to_country.upper()})\n"
            f"- **Collection**: {collection_date}\n"
            f"- **Content**: {content} (€{content_value:.2f})\n\n"
            f"Use `packlink_label(reference=\"{ref}\")` to get the shipping label."
        )


# ---------------------------------------------------------------------------
# Label
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "reference": {"type": "string", "description": "Packlink shipment reference (e.g. IT2026PRO...)"},
    },
    "required": ["reference"],
})
class PacklinkLabelTool(Tool):
    """Get the PDF label URL for a Packlink shipment."""

    name = "packlink_label"
    description = (
        "Get the PDF label download URL for a Packlink shipment. "
        "The label is needed to ship the package."
    )
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(os.environ.get("PACKLINK_API_KEY"))

    @classmethod
    def create(cls, ctx: Any) -> "PacklinkLabelTool":
        return cls()

    async def execute(self, reference: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BASE_URL}/shipments/{reference}/labels",
                headers=_headers(),
            )
            if resp.status_code == 404:
                return f"Shipment `{reference}` not found or label not yet ready."
            resp.raise_for_status()
            data = resp.json()

        if isinstance(data, list) and data:
            urls = "\n".join(f"- {url}" for url in data)
            return f"## Label for `{reference}`\n{urls}"
        if isinstance(data, dict):
            url = data.get("pdf") or data.get("url") or str(data)
            return f"## Label for `{reference}`\n- {url}"
        return f"Label data: {data}"


# ---------------------------------------------------------------------------
# Track
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "reference": {"type": "string", "description": "Packlink shipment reference"},
    },
    "required": ["reference"],
})
class PacklinkTrackTool(Tool):
    """Get the current status of a Packlink shipment."""

    name = "packlink_track"
    description = "Get the current status and tracking info for a Packlink shipment."
    _scopes = {"core"}

    @classmethod
    def enabled(cls, ctx: Any) -> bool:
        return bool(os.environ.get("PACKLINK_API_KEY"))

    @classmethod
    def create(cls, ctx: Any) -> "PacklinkTrackTool":
        return cls()

    async def execute(self, reference: str) -> str:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_BASE_URL}/shipments/{reference}",
                headers=_headers(),
            )
            if resp.status_code == 404:
                return f"Shipment `{reference}` not found."
            resp.raise_for_status()
            s = resp.json()

        state = s.get("state", "unknown")
        status_desc = state if isinstance(state, str) else (state.get("description") or state.get("id", "unknown"))
        to = s.get("to", {})
        carrier = s.get("carrier") or s.get("carrier_id", "")
        trackings = s.get("trackings") or s.get("tracking_codes", [])
        tracking_url_tpl = s.get("tracking_url", "")
        estimated = s.get("estimated_delivery_date", "")

        lines = [
            f"## Shipment `{reference}`",
            f"- **Status**: {status_desc}",
            f"- **To**: {to.get('name','')} {to.get('surname','')}, {to.get('city','')} ({to.get('country','')})",
        ]
        if carrier:
            lines.append(f"- **Carrier**: {carrier}")
        if estimated:
            lines.append(f"- **Estimated delivery**: {estimated}")
        if trackings:
            lines.append(f"- **Carrier tracking**: {', '.join(str(t) for t in trackings)}")
        # Build the carrier tracking URL by substituting the template placeholder
        if tracking_url_tpl and trackings:
            carrier_url = tracking_url_tpl.replace("[[trackingNumber]]", str(trackings[0]))
            lines.append(f"- **Carrier tracking URL**: {carrier_url}")

        return "\n".join(lines)
