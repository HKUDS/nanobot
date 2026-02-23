"""OKX Trading System Skill."""

import json
import hmac
import base64
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx


class OKXTradeSkill:
    """OKX trading operations skill."""

    def __init__(self, config_path: str | None = None):
        """Initialize OKX trading skill."""
        if config_path is None:
            # Try user workspace first, then fall back to package location
            user_config = Path.home() / ".nanobot" / "workspace" / "skills" / "okx_trade" / "config.json"
            if user_config.exists():
                config_path = user_config
            else:
                config_path = Path(__file__).parent / "config.json"
        else:
            config_path = Path(config_path)

        if not config_path.exists():
            raise FileNotFoundError(
                f"Config file not found at {config_path}. "
                f"Please copy config.example.json to config.json and fill in your API credentials."
            )

        with open(config_path) as f:
            self.config = json.load(f)

        self.api_key = self.config["api_key"]
        self.secret_key = self.config["secret_key"]
        self.passphrase = self.config["passphrase"]
        self.is_demo = self.config.get("is_demo", True)

        # Use demo trading if enabled
        if self.is_demo:
            self.base_url = "https://www.okx.com"  # Demo uses same endpoint with x-simulated-trading header
        else:
            self.base_url = self.config.get("base_url", "https://www.okx.com")

    def _sign(self, timestamp: str, method: str, request_path: str, body: str = "") -> str:
        """Generate signature for OKX API request.

        According to OKX docs: timestamp + method + requestPath + body
        Example: 2024-01-01T00:00:00.000ZGET/api/v5/account/balance
        """
        # Ensure body is empty string for GET requests
        if not body:
            body = ""

        # Build prehash string: timestamp + method + requestPath + body
        # NO newlines, NO API-KEY field - just simple concatenation
        prehash_string = timestamp + method + request_path + body

        # Sign with HMAC-SHA256
        mac = hmac.new(
            self.secret_key.encode("utf-8"),
            prehash_string.encode("utf-8"),
            hashlib.sha256
        )
        return base64.b64encode(mac.digest()).decode()

    def _get_headers(self, method: str, request_path: str, body: str = "") -> dict[str, str]:
        """Generate headers for OKX API request."""
        # OKX requires ISO 8601 timestamp: 2024-01-01T00:00:00.123Z
        # Must be UTC time with milliseconds
        from datetime import timezone
        now = datetime.now(timezone.utc)
        timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

        signature = self._sign(timestamp, method, request_path, body)

        headers = {
            "OK-ACCESS-KEY": self.api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self.passphrase,
            "Content-Type": "application/json",
        }

        if self.is_demo:
            headers["x-simulated-trading"] = "1"

        return headers

    async def get_account_balance(self) -> dict[str, Any]:
        """Get account balance."""
        request_path = "/api/v5/account/balance"
        headers = self._get_headers("GET", request_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{request_path}",
                headers=headers
            )
            return response.json()

    async def get_positions(self, inst_type: str = "SWAP") -> dict[str, Any]:
        """Get current positions.

        Args:
            inst_type: Instrument type (SPOT, MARGIN, SWAP, FUTURES, OPTION)
        """
        request_path = f"/api/v5/account/positions?instType={inst_type}"
        headers = self._get_headers("GET", request_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{request_path}",
                headers=headers
            )
            return response.json()

    async def place_order(
        self,
        inst_id: str,
        side: str,
        order_type: str,
        size: str,
        price: str | None = None,
        td_mode: str = "cross",
    ) -> dict[str, Any]:
        """Place an order.

        Args:
            inst_id: Instrument ID (e.g., "BTC-USDT-SWAP")
            side: Order side ("buy" or "sell")
            order_type: Order type ("market", "limit", "post_only", etc.)
            size: Order size
            price: Order price (required for limit orders)
            td_mode: Trade mode ("cross", "isolated", "cash")
        """
        request_path = "/api/v5/trade/order"

        body_data = {
            "instId": inst_id,
            "tdMode": td_mode,
            "side": side,
            "ordType": order_type,
            "sz": size,
        }

        if price:
            body_data["px"] = price

        body = json.dumps(body_data)
        headers = self._get_headers("POST", request_path, body)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}{request_path}",
                headers=headers,
                content=body
            )
            return response.json()

    async def cancel_order(self, inst_id: str, order_id: str) -> dict[str, Any]:
        """Cancel an order.

        Args:
            inst_id: Instrument ID
            order_id: Order ID to cancel
        """
        request_path = "/api/v5/trade/cancel-order"

        body_data = {
            "instId": inst_id,
            "ordId": order_id,
        }

        body = json.dumps(body_data)
        headers = self._get_headers("POST", request_path, body)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}{request_path}",
                headers=headers,
                content=body
            )
            return response.json()

    async def get_order_history(
        self,
        inst_type: str = "SWAP",
        limit: int = 100
    ) -> dict[str, Any]:
        """Get order history.

        Args:
            inst_type: Instrument type
            limit: Number of results (max 100)
        """
        request_path = f"/api/v5/trade/orders-history?instType={inst_type}&limit={limit}"
        headers = self._get_headers("GET", request_path)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{request_path}",
                headers=headers
            )
            return response.json()

    async def get_ticker(self, inst_id: str) -> dict[str, Any]:
        """Get ticker information.

        Args:
            inst_id: Instrument ID (e.g., "BTC-USDT-SWAP")
        """
        request_path = f"/api/v5/market/ticker?instId={inst_id}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self.base_url}{request_path}"
            )
            return response.json()
