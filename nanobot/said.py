"""
SAID Protocol integration for nanobot.

Registers the agent with SAID Protocol on startup and increments
activity count on each processed message — building on-chain reputation
and qualifying for Layer 2 verification over time.

SAID Protocol: on-chain identity, reputation, and verification for AI agents
on Solana. https://saidprotocol.com

Config (in ~/.nanobot/config.json under agents.said):

    "agents": {
        "said": {
            "enabled": true,
            "wallet": "<solana-wallet-pubkey>",
            "agentName": "My Nanobot"
        }
    }
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

SAID_API_BASE = "https://api.saidprotocol.com"
SAID_REGISTRATION_SOURCE = "nanobot"


def _post(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "nanobot-said/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(body)
        except Exception:
            return {"error": body}
    except Exception as e:
        return {"error": str(e)}


class SAIDIdentity:
    """Manages SAID Protocol identity for a nanobot agent."""

    def __init__(self, wallet: str, agent_name: str, description: str = "") -> None:
        self.wallet = wallet
        self.agent_name = agent_name
        self.description = description or f"{agent_name} — nanobot AI agent on SAID Protocol"
        self._registered = False

    def register(self) -> bool:
        """Register (or verify existing) agent on SAID Protocol. Free, non-blocking."""
        if not self.wallet or not self.agent_name:
            return False

        logger.info(f"SAID: registering {self.agent_name} ({self.wallet[:8]}...)")
        result = _post(f"{SAID_API_BASE}/api/register/pending", {
            "wallet": self.wallet,
            "name": self.agent_name,
            "description": self.description,
            "source": SAID_REGISTRATION_SOURCE,
        })

        if result.get("success") or result.get("pda") or "already registered" in result.get("error", "").lower():
            self._registered = True
            profile = result.get("profile", f"https://saidprotocol.com/agent.html?wallet={self.wallet}")
            logger.info(f"SAID: registered ✓  {profile}")
            return True

        logger.debug(f"SAID: registration skipped — {result.get('error', result)}")
        return False

    def ping(self) -> None:
        """Increment activity counter — called on each agent interaction."""
        if not self._registered:
            return
        try:
            _post(f"{SAID_API_BASE}/api/verify/layer2/activity/{self.wallet}", {})
        except Exception:
            pass

    @property
    def profile_url(self) -> str:
        return f"https://saidprotocol.com/agent.html?wallet={self.wallet}"
