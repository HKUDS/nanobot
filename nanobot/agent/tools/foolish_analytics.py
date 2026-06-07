"""Foolish Analytics — queries Umami for The Foolish Butcher storefront metrics.

Exposes one agent-callable tool:
  foolish_analytics  — pageviews, visitors, e-commerce funnel events, top pages,
                       abandoned carts, orders completed (from storefront DB API)

Required env vars:
  FOOLISH_UMAMI_URL         e.g. https://umami-production-8b53.up.railway.app
  FOOLISH_UMAMI_PASSWORD    password set at first Umami login
  FOOLISH_UMAMI_WEBSITE_ID  e.g. 764cb6b5-a16f-4dc6-b144-449b43e102fa
  FOOLISH_UMAMI_USERNAME    default: admin
  FOOLISH_PAYLOAD_SECRET    shared secret for storefront API (x-storefront-secret header)
  FOOLISH_STOREFRONT_URL    e.g. https://thefoolishbutcher.com (default)
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _base_url() -> str:
    return os.environ.get("FOOLISH_UMAMI_URL", "").rstrip("/")

def _credentials() -> tuple[str, str]:
    user = os.environ.get("FOOLISH_UMAMI_USERNAME", "admin")
    pwd  = os.environ.get("FOOLISH_UMAMI_PASSWORD", "")
    return user, pwd

def _website_id() -> str:
    return os.environ.get("FOOLISH_UMAMI_WEBSITE_ID", "")

def _storefront_url() -> str:
    return os.environ.get("FOOLISH_STOREFRONT_URL", "https://thefoolishbutcher.com").rstrip("/")

def _payload_secret() -> str:
    return os.environ.get("FOOLISH_PAYLOAD_SECRET", "")


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _period_range(period: str) -> tuple[int, int]:
    """Return (start_ms, end_ms) for the requested period."""
    now = datetime.now(tz=timezone.utc)
    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = now
    elif period == "yesterday":
        d     = now - timedelta(days=1)
        start = d.replace(hour=0,  minute=0,  second=0,  microsecond=0)
        end   = d.replace(hour=23, minute=59, second=59, microsecond=0)
    elif period == "7d":
        start = now - timedelta(days=7)
        end   = now
    elif period == "30d":
        start = now - timedelta(days=30)
        end   = now
    else:
        start = now - timedelta(days=1)
        end   = now
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

async def _get_token(client: httpx.AsyncClient, base: str) -> str:
    user, pwd = _credentials()
    resp = await client.post(
        f"{base}/api/auth/login",
        json={"username": user, "password": pwd},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["token"]


async def _fetch_all(
    client: httpx.AsyncClient,
    base: str,
    wid: str,
    token: str,
    start_ms: int,
    end_ms: int,
) -> tuple[dict, list, list]:
    headers = {"Authorization": f"Bearer {token}"}
    base_params = {"startAt": start_ms, "endAt": end_ms}

    stats_req  = client.get(f"{base}/api/websites/{wid}/stats",
                            headers=headers, params=base_params)
    # /metrics?type=event returns aggregated counts {x: eventName, y: count}
    events_req = client.get(f"{base}/api/websites/{wid}/metrics",
                            headers=headers,
                            params={**base_params, "type": "event", "limit": 50})

    stats_r, events_r = await asyncio.gather(stats_req, events_req)
    stats_r.raise_for_status()
    events_r.raise_for_status()

    ev_raw = events_r.json()
    events = ev_raw if isinstance(ev_raw, list) else ev_raw.get("data", [])

    # Top pages — /metrics?type=url broken on this Umami version; skip gracefully
    pages: list = []

    return stats_r.json(), events, pages


# ---------------------------------------------------------------------------
# DB cart / order stats from storefront API
# ---------------------------------------------------------------------------

async def _fetch_cart_stats(client: httpx.AsyncClient) -> dict | None:
    secret = _payload_secret()
    if not secret:
        return None
    try:
        resp = await client.get(
            f"{_storefront_url()}/api/marketing/stats",
            headers={"x-storefront-secret": secret},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Cart stats API error: {}", exc)
        return None


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _pct(num: int, den: int) -> str:
    return f"{round(num / den * 100, 1)}%" if den else "n/d"


def _format_report(
    period: str,
    stats: dict,
    events: list,
    pages: list,
    cart_stats: dict | None = None,
) -> str:
    label = {
        "today":     "oggi",
        "yesterday": "ieri",
        "7d":        "ultimi 7 giorni",
        "30d":       "ultimi 30 giorni",
    }.get(period, period)

    def _sv(v) -> int:
        """Stats value — handles both flat int and {"value": N} formats."""
        if isinstance(v, dict):
            return int(v.get("value", 0))
        return int(v or 0)

    pv       = _sv(stats.get("pageviews"))
    uv       = _sv(stats.get("visitors"))
    sessions = _sv(stats.get("visits"))
    bounces  = _sv(stats.get("bounces"))
    tot_time = _sv(stats.get("totaltime"))

    bounce_pct = f"{round(bounces  / sessions * 100)}%" if sessions else "n/d"
    avg_dur    = f"{round(tot_time / sessions)}s"        if sessions else "n/d"

    # Aggregate event counts
    ev: dict[str, int] = {}
    for e in events:
        name = e.get("x") or e.get("eventName") or e.get("name", "")
        cnt  = int(e.get("y") or e.get("count") or 0)
        if name:
            ev[name] = ev.get(name, 0) + cnt

    add_to_cart      = ev.get("add_to_cart",      0)
    pack_added       = ev.get("pack_added",        0)
    checkout_started = ev.get("checkout_started",  0)
    order_completed  = ev.get("order_completed",   0)
    variant_selected = ev.get("variant_selected",  0)

    lines = [
        f"## Analytics Foolish — {label}",
        "",
        f"**Traffico:** {pv} pageview · {uv} visitatori · {sessions} sessioni",
        f"**Bounce rate:** {bounce_pct} · **Durata media sessione:** {avg_dur}",
        "",
        "### Funnel e-commerce (Umami)",
        f"- `variant_selected` — {variant_selected}",
        f"- `add_to_cart` — {add_to_cart}  ({_pct(add_to_cart, uv)} visitatori)",
        f"- `pack_added` — {pack_added}",
        f"- `checkout_started` — {checkout_started}  ({_pct(checkout_started, add_to_cart)} di chi ha aggiunto al carrello)",
        f"- `order_completed` — {order_completed}  ({_pct(order_completed, checkout_started)} di chi ha avviato il checkout)",
        f"- **Conversion rate totale** (visitatori → ordine): {_pct(order_completed, uv)}",
    ]

    if cart_stats:
        carts_today    = cart_stats.get("carts_active_today", 0)
        carts_aband    = cart_stats.get("carts_abandoned_7d", 0)
        orders_today   = cart_stats.get("orders_today", 0)
        orders_7d      = cart_stats.get("orders_7d", 0)
        revenue_7d     = cart_stats.get("revenue_7d", 0.0)
        lines += [
            "",
            "### Carrelli & Ordini (DB live)",
            f"- Carrelli avviati oggi: **{carts_today}**",
            f"- Carrelli abbandonati (ultimi 7gg, >1h fa): **{carts_aband}**",
            f"- Ordini completati oggi: **{orders_today}**",
            f"- Ordini completati (ultimi 7gg): **{orders_7d}** · Revenue: **{revenue_7d:.2f}€**",
        ]

    if pages:
        lines += ["", "### Pagine più visitate"]
        for p in pages[:5]:
            url   = p.get("x") or p.get("url", "?")
            count = p.get("y") or p.get("visitors", 0)
            lines.append(f"  - `{url}` — {count} visite")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------

@tool_parameters({
    "type": "object",
    "properties": {
        "period": {
            "type": "string",
            "enum": ["today", "yesterday", "7d", "30d"],
            "description": (
                "Periodo temporale da analizzare: "
                "today (da mezzanotte a ora), "
                "yesterday (giorno precedente, default), "
                "7d (ultimi 7 giorni), "
                "30d (ultimi 30 giorni)."
            ),
        }
    },
    "required": [],
})
class FoolishAnalyticsTool(Tool):
    """Analytics on-demand per The Foolish Butcher."""

    name = "foolish_analytics"
    description = (
        "Recupera le metriche analytics del sito The Foolish Butcher: "
        "visite, visitatori unici, bounce rate, durata sessione, "
        "e funnel e-commerce (variant_selected, add_to_cart, pack_added, checkout_started). "
        "Usa quando Alessandro chiede 'com'è andata ieri', 'quante vendite questa settimana', "
        "'che conversion rate abbiamo', ecc."
    )
    _scopes = {"foolish"}

    @classmethod
    def enabled(cls, ctx) -> bool:
        return bool(_base_url() and _credentials()[1] and _website_id())

    async def execute(self, period: str = "yesterday") -> str:
        base = _base_url()
        wid  = _website_id()
        _, pwd = _credentials()

        if not (base and pwd and wid):
            return (
                "Errore: variabili d'ambiente Umami non configurate. "
                "Servono: FOOLISH_UMAMI_URL, FOOLISH_UMAMI_PASSWORD, FOOLISH_UMAMI_WEBSITE_ID."
            )

        start_ms, end_ms = _period_range(period)

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token = await _get_token(client, base)
                stats, events, pages = await _fetch_all(
                    client, base, wid, token, start_ms, end_ms
                )
                cart_stats = await _fetch_cart_stats(client)
        except httpx.HTTPStatusError as exc:
            logger.error("Umami API HTTP error: {}", exc)
            return f"Errore API Umami: HTTP {exc.response.status_code} — {exc.response.text[:300]}"
        except Exception as exc:
            logger.error("Umami connection error: {}", exc)
            return f"Errore connessione Umami: {exc}"

        return _format_report(period, stats, events, pages, cart_stats)
