"""Nostr channel implementation using NIP-17 Gift Wrap DM."""

import asyncio
import base64
import hashlib
import json
import random
import secrets
import ssl
import struct
import time
from collections import OrderedDict

import os
import aiohttp
import secp256k1
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.hmac import HMAC as _HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from loguru import logger
from pydantic import Field

from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import NostrConfig


# ── Default relay list ────────────────────────────────────────────────────────

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://relay.0xchat.com",
    "wss://nostr.oxtr.dev",
    "wss://nostr-pub.wellorder.net",
    "wss://relay.primal.net",
]

HISTORY_SECS = 7 * 24 * 3600  # Fetch messages from the last 7 days

# Respect standard proxy environment variables
PROXY = (
    os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy") or
    os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or
    os.environ.get("ALL_PROXY")   or os.environ.get("all_proxy")
)

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE

# ── bech32 helpers ────────────────────────────────────────────────────────────

_CS = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_CM = {c: i for i, c in enumerate(_CS)}
_GN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3]


def _pm(vals):
    c = 1
    for v in vals:
        b = c >> 25
        c = (c & 0x1ffffff) << 5 ^ v
        for i in range(5):
            c ^= _GN[i] if (b >> i) & 1 else 0
    return c


def _hrp(h):
    return [ord(x) >> 5 for x in h] + [0] + [ord(x) & 31 for x in h]


def _bits(data, f, t, pad=True):
    a = bits = 0
    r = []
    mx = (1 << t) - 1
    for v in data:
        a = (a << f) | v
        bits += f
        while bits >= t:
            bits -= t
            r.append((a >> bits) & mx)
    if pad and bits:
        r.append((a << (t - bits)) & mx)
    return r


def _b32enc(hrp, data):
    d = _bits(data, 8, 5)
    p = _pm(_hrp(hrp) + d + [0] * 6) ^ 1
    return hrp + "1" + "".join(_CS[x] for x in d + [(p >> 5 * (5 - i)) & 31 for i in range(6)])


def _b32dec(s):
    s = s.lower()
    p = s.rfind("1")
    if p < 1 or p + 7 > len(s):
        raise ValueError("bad bech32")
    hrp = s[:p]
    try:
        d = [_CM[c] for c in s[p + 1:]]
    except KeyError:
        raise ValueError("bad char")
    if _pm(_hrp(hrp) + d) != 1:
        raise ValueError("bad checksum")
    return hrp, bytes(_bits(d[:-6], 5, 8, pad=False))


def to_npub(hex_pub: str) -> str:
    return _b32enc("npub", bytes.fromhex(hex_pub))


def npub_to_hex(npub: str) -> str:
    hrp, b = _b32dec(npub)
    if hrp != "npub":
        raise ValueError("not an npub")
    return b.hex()


def nsec_to_hex(nsec: str) -> str:
    hrp, b = _b32dec(nsec)
    if hrp != "nsec":
        raise ValueError("not an nsec")
    return b.hex()


def derive_pub(priv_hex: str) -> str:
    return secp256k1.PrivateKey(bytes.fromhex(priv_hex)).pubkey.serialize()[1:].hex()


# ── Crypto primitives ─────────────────────────────────────────────────────────

def _schnorr(eid: str, priv: str) -> str:
    return secp256k1.PrivateKey(bytes.fromhex(priv)).schnorr_sign(
        bytes.fromhex(eid), None, raw=True
    ).hex()


def _ecdh(priv: str, pub: str) -> bytes:
    pk = secp256k1.PublicKey(bytes.fromhex("02" + pub), raw=True)
    return pk.tweak_mul(
        secp256k1.PrivateKey(bytes.fromhex(priv)).private_key
    ).serialize(compressed=True)[1:]


def _ev_id(ev: dict) -> str:
    s = json.dumps(
        [0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
        separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(s.encode()).hexdigest()


def _mkevent(kind: int, content: str, priv: str, pub: str, tags=None) -> dict:
    ev = {"pubkey": pub, "created_at": int(time.time()),
          "kind": kind, "tags": tags or [], "content": content}
    ev["id"] = _ev_id(ev)
    ev["sig"] = _schnorr(ev["id"], priv)
    return ev


def _gen_keys() -> tuple[str, str]:
    b = secrets.token_bytes(32)
    return b.hex(), secp256k1.PrivateKey(b).pubkey.serialize()[1:].hex()


# ── NIP-44 v2 ─────────────────────────────────────────────────────────────────

def _nip44_conv_key(priv: str, pub: str) -> bytes:
    h = _HMAC(b"nip44-v2", SHA256(), backend=default_backend())
    h.update(_ecdh(priv, pub))
    return h.finalize()


def _nip44_pad_len(l: int) -> int:
    if l <= 32:
        return 32
    np = 1 << (l - 1).bit_length()
    chunk = max(np // 8, 32)
    return chunk * ((l - 1) // chunk + 1)


def _nip44_enc(text: str, priv: str, pub: str) -> str:
    ck = _nip44_conv_key(priv, pub)
    nonce = secrets.token_bytes(32)
    keys = HKDFExpand(SHA256(), 76, nonce, default_backend()).derive(ck)
    ck2, cn, hk = keys[:32], keys[32:44], keys[44:]
    plain = text.encode()
    pl = _nip44_pad_len(len(plain))
    padded = struct.pack(">H", len(plain)) + plain + b"\x00" * (pl - len(plain))
    enc = Cipher(algorithms.ChaCha20(ck2, b"\x00\x00\x00\x00" + cn), None, default_backend()).encryptor()
    ct = enc.update(padded) + enc.finalize()
    hm = _HMAC(hk, SHA256(), backend=default_backend())
    hm.update(nonce + ct)
    return base64.b64encode(b"\x02" + nonce + ct + hm.finalize()).decode()


def _nip44_dec(payload: str, priv: str, pub: str) -> str:
    raw = base64.b64decode(payload)
    if raw[0] != 2:
        raise ValueError("unsupported nip44 version")
    nonce, ct, mac = raw[1:33], raw[33:-32], raw[-32:]
    ck = _nip44_conv_key(priv, pub)
    keys = HKDFExpand(SHA256(), 76, nonce, default_backend()).derive(ck)
    ck2, cn, hk = keys[:32], keys[32:44], keys[44:]
    hm = _HMAC(hk, SHA256(), backend=default_backend())
    hm.update(nonce + ct)
    if not secrets.compare_digest(mac, hm.finalize()):
        raise ValueError("bad mac")
    dec = Cipher(algorithms.ChaCha20(ck2, b"\x00\x00\x00\x00" + cn), None, default_backend()).decryptor()
    padded = dec.update(ct) + dec.finalize()
    l = struct.unpack(">H", padded[:2])[0]
    return padded[2:2 + l].decode()


# ── NIP-17 Gift Wrap ──────────────────────────────────────────────────────────

def _rand_ts() -> int:
    # Randomize timestamp within the past 48 hours to improve metadata privacy
    return int(time.time()) - random.randint(0, 172800)


def nip17_wrap(text: str, sender_priv: str, sender_pub: str, recipient_pub: str) -> dict:
    """
    Wrap a plaintext message into a NIP-17 Gift Wrap event (kind:1059).

    Flow: Rumor (kind:14, unsigned) -> Seal (kind:13, NIP-44) -> Gift Wrap (kind:1059, ephemeral key)
    """
    # 1. Rumor (kind:14, unsigned)
    rumor = {
        "pubkey": sender_pub, "created_at": int(time.time()),
        "kind": 14, "tags": [["p", recipient_pub]], "content": text,
    }
    rumor["id"] = _ev_id(rumor)

    # 2. Seal (kind:13, signed by sender, NIP-44 encrypted rumor)
    seal = {
        "pubkey": sender_pub, "created_at": _rand_ts(),
        "kind": 13, "tags": [],
        "content": _nip44_enc(json.dumps(rumor), sender_priv, recipient_pub),
    }
    seal["id"] = _ev_id(seal)
    seal["sig"] = _schnorr(seal["id"], sender_priv)

    # 3. Gift Wrap (kind:1059, signed by ephemeral key, NIP-44 encrypted seal)
    eph_priv, eph_pub = _gen_keys()
    wrap = {
        "pubkey": eph_pub, "created_at": _rand_ts(),
        "kind": 1059, "tags": [["p", recipient_pub]],
        "content": _nip44_enc(json.dumps(seal), eph_priv, recipient_pub),
    }
    wrap["id"] = _ev_id(wrap)
    wrap["sig"] = _schnorr(wrap["id"], eph_priv)
    return wrap


def nip17_unwrap(wrap_ev: dict, my_priv: str) -> tuple[dict, str]:
    """Unwrap a NIP-17 Gift Wrap event. Returns (rumor, sender_hex_pub)."""
    seal_json = _nip44_dec(wrap_ev["content"], my_priv, wrap_ev["pubkey"])
    seal = json.loads(seal_json)
    if seal.get("kind") != 13:
        raise ValueError(f"expected kind:13, got {seal.get('kind')}")
    rumor_json = _nip44_dec(seal["content"], my_priv, seal["pubkey"])
    rumor = json.loads(rumor_json)
    if rumor.get("kind") != 14:
        raise ValueError(f"expected kind:14, got {rumor.get('kind')}")
    return rumor, seal["pubkey"]


# ── Relay pool ────────────────────────────────────────────────────────────────

class _RelayPool:
    """Minimal relay pool: connect to configured relays, subscribe to kind:1059, publish events."""

    def __init__(self, my_pub: str, relays: list[str], on_event):
        self._pub = my_pub
        self._relays = relays
        self._on_event = on_event
        self._conns: dict[str, aiohttp.ClientWebSocketResponse] = {}
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._tasks: list[asyncio.Task] = []
        self._sess: aiohttp.ClientSession | None = None
        self._running = False
        self._t0 = int(time.time())

    async def start(self) -> None:
        self._running = True
        self._sess = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60, connect=15, sock_read=60),
            connector=aiohttp.TCPConnector(ssl=_SSL) if PROXY else None,
        )
        for url in self._relays:
            self._tasks.append(asyncio.create_task(self._connect(url)))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for ws in list(self._conns.values()):
            try:
                await ws.close()
            except Exception:
                pass
        self._conns.clear()
        if self._sess and not self._sess.closed:
            await self._sess.close()
            await asyncio.sleep(0.1)

    async def publish(self, ev: dict) -> int:
        msg = json.dumps(["EVENT", ev])
        ok = 0
        for ws in list(self._conns.values()):
            try:
                await ws.send_str(msg)
                ok += 1
            except Exception:
                pass
        return ok

    @property
    def connected(self) -> int:
        return len(self._conns)

    async def _connect(self, url: str) -> None:
        backoff = 2
        while self._running:
            try:
                kw: dict = {"headers": {"User-Agent": "NostrBot/1.0"}}
                if PROXY:
                    kw["proxy"] = PROXY
                async with self._sess.ws_connect(url, ssl=_SSL, **kw) as ws:
                    self._conns[url] = ws
                    backoff = 2
                    logger.debug("Nostr relay connected: {}", url)
                    await self._subscribe(ws)
                    ping = asyncio.create_task(self._ping(ws, url))
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._handle(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                break
                    finally:
                        ping.cancel()
                        try:
                            await ping
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.warning("Nostr relay {} error: {}", url, e)
            finally:
                self._conns.pop(url, None)
            if self._running:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _ping(self, ws, url: str) -> None:
        """Send a WebSocket ping every 30 seconds. Close the connection on timeout."""
        while True:
            await asyncio.sleep(30)
            try:
                await asyncio.wait_for(ws.ping(), timeout=10)
                logger.debug("Nostr relay {} ping ok", url)
            except asyncio.TimeoutError:
                logger.warning("Nostr relay {} ping timeout, dropping connection", url)
                await ws.close()
                break
            except Exception:
                break

    async def _subscribe(self, ws) -> None:
        since_hist = int(time.time()) - HISTORY_SECS
        sid = secrets.token_hex(8)
        # 1. Historical messages: kind:1059 addressed to us, within the past 7 days
        await ws.send_str(json.dumps([
            "REQ", sid,
            {"kinds": [1059], "#p": [self._pub], "since": since_hist, "limit": 0},
        ]))
        # 2. Live messages: kind:1059 addressed to us, from this moment onward
        sid2 = secrets.token_hex(8)
        await ws.send_str(json.dumps([
            "REQ", sid2,
            {"kinds": [1059], "#p": [self._pub], "since": self._t0, "limit": 0},
        ]))

    async def _handle(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except Exception:
            return
        if not isinstance(msg, list) or not msg:
            return
        if msg[0] == "EVENT" and len(msg) >= 3:
            ev = msg[2]
            eid = ev.get("id", "")
            if eid and eid not in self._seen:
                self._seen[eid] = time.time()
                # Prune seen cache to avoid unbounded growth
                if len(self._seen) > 5000:
                    for k in list(self._seen.keys())[:500]:
                        del self._seen[k]
                await self._on_event(ev)


# ── Channel ───────────────────────────────────────────────────────────────────

class NostrChannel(BaseChannel):
    """
    Nostr channel using NIP-17 Gift Wrap DMs (kind:1059).

    Each conversation participant is identified by their npub.
    The bot's identity is configured via the `nsec` field in NostrConfig.
    Relays are configured via the `relays` field in NostrConfig.
    """

    name = "nostr"

    def __init__(self, config: NostrConfig, bus: MessageBus):
        super().__init__(config, bus)
        self.config: NostrConfig = config

        # Resolve private / public key
        raw = config.nsec.strip()
        if raw.startswith("nsec1"):
            self._priv = nsec_to_hex(raw)
        elif len(raw) == 64:
            self._priv = raw
        else:
            raise ValueError("NostrConfig.nsec must be nsec1... bech32 or 64-char hex")

        self._pub = derive_pub(self._priv)
        self._npub = to_npub(self._pub)

        relays = config.relays or DEFAULT_RELAYS
        logger.info("Nostr bot identity: {} | relays: {}", self._npub, len(relays))

        self._pool = _RelayPool(self._pub, relays, self._on_relay_event)
        self._processed_ids: OrderedDict[str, None] = OrderedDict()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to all configured relays and start listening for Gift Wrap DMs."""
        self._running = True
        logger.info("Starting Nostr channel ({} relays)...", len(self.config.relays or DEFAULT_RELAYS))
        await self._pool.start()
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Disconnect from all relays."""
        self._running = False
        await self._pool.stop()
        logger.info("Nostr channel stopped.")

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send(self, msg: OutboundMessage) -> None:
        """Send a NIP-17 Gift Wrap DM to the recipient identified by npub in chat_id."""
        if self._pool.connected == 0:
            logger.warning("Nostr: no relay connected, cannot send message")
            return

        try:
            recipient_hex = npub_to_hex(msg.chat_id)
        except Exception as e:
            logger.error("Nostr send: invalid chat_id '{}': {}", msg.chat_id, e)
            return

        try:
            wrap = nip17_wrap(msg.content, self._priv, self._pub, recipient_hex)
            ok = await self._pool.publish(wrap)
            logger.debug("Nostr NIP-17 DM sent to {} via {} relay(s)", msg.chat_id[:20], ok)
        except Exception as e:
            logger.error("Nostr send error: {}", e)

    # ── Receive ───────────────────────────────────────────────────────────────

    async def _on_relay_event(self, ev: dict) -> None:
        """Called by the relay pool for every new kind:1059 event."""
        if ev.get("kind") != 1059:
            return

        event_id = ev.get("id", "")
        if event_id:
            if event_id in self._processed_ids:
                return
            self._processed_ids[event_id] = None
            while len(self._processed_ids) > 1000:
                self._processed_ids.popitem(last=False)

        try:
            rumor, sender_hex = nip17_unwrap(ev, self._priv)
        except Exception as e:
            logger.warning("Nostr: NIP-17 unwrap failed (id={}): {}", event_id[:12], e)
            return

        content = rumor.get("content", "").strip()
        if not content:
            return

        sender_npub = to_npub(sender_hex)
        await self._handle_message(
            sender_id=sender_npub,
            chat_id=sender_npub,
            content=content,
            metadata={
                "event_id": event_id,
                "rumor_id": rumor.get("id", ""),
                "timestamp": rumor.get("created_at"),
                "protocol": "nip17",
            },
        )