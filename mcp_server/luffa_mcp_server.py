#!/usr/bin/env python3
"""
Luffa Fake MCP Server — Fixed for Nanobot (mcp SDK >= 1.0)
===========================================================
ROOT CAUSE OF THE BUG:
  Nanobot uses the official Anthropic MCP Python SDK (mcp >= 1.0).
  That SDK frames stdio messages with Content-Length headers (LSP-style):

      Content-Length: 97\r\n
      \r\n
      {"jsonrpc":"2.0","id":1,"method":"initialize",...}

  The original server read bare JSON lines so it never saw the messages —
  the client hung waiting for a response that never came.

FIX: Two things changed:
  1. read_message() / send_message() use Content-Length framing
  2. After initialize response, server sends notifications/initialized
     so the SDK handshake fully completes
"""

import json, sys, random, logging
from datetime import datetime, timedelta

logging.basicConfig(
    filename="luffa_mcp.log", level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("luffa-mcp")

# ── Content-Length framed I/O  (THE FIX) ────────────────────

# def read_message():
#     """Read one Content-Length framed JSON-RPC message from stdin."""
#     headers = {}
#     while True:
#         line = sys.stdin.buffer.readline()
#         if not line:
#             return None                      # EOF
        
#         line = line.rstrip(b"\r\n")
#         if line == b"":
#             if not headers:
#                 continue                     # FIXED: Ignore stray newlines between messages
#             break                            # blank line after headers = end of headers
            
#         if b":" in line:
#             k, _, v = line.partition(b":")
#             headers[k.strip().lower()] = v.strip()

#     length = int(headers.get(b"content-length", 0))
#     if length == 0:
#         return None

#     raw = sys.stdin.buffer.read(length)
#     log.info(f"RECV: {raw.decode()}")
#     return json.loads(raw.decode("utf-8"))
USE_FRAMING = None  # Will auto-detect based on the first message

def read_message():
    global USE_FRAMING
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None  # EOF (Client closed connection)

        # Auto-detect Bare JSON Line (starts with '{')
        if not headers and line.lstrip().startswith(b"{"):
            USE_FRAMING = False
            decoded = line.decode("utf-8").strip()
            log.info(f"RECV (Bare JSON): {decoded}")
            return json.loads(decoded)

        line = line.rstrip(b"\r\n")
        if line == b"":
            if not headers:
                continue                     # Ignore stray blank lines
            break                            # Blank line ends headers
            
        if b":" in line:
            USE_FRAMING = True
            k, _, v = line.partition(b":")
            headers[k.strip().lower()] = v.strip()

    length = int(headers.get(b"content-length", 0))
    if length == 0:
        return None

    raw = sys.stdin.buffer.read(length)
    log.info(f"RECV (Framed): {raw.decode('utf-8')}")
    return json.loads(raw.decode("utf-8"))

# def send_message(obj):
#     """Write one Content-Length framed JSON-RPC message to stdout."""
#     body   = json.dumps(obj, ensure_ascii=False).encode("utf-8")
#     header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
#     sys.stdout.buffer.write(header + body)
#     sys.stdout.buffer.flush()
#     log.info(f"SENT: {body.decode()}")

def send_message(obj):
    global USE_FRAMING
    body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    
    if USE_FRAMING is False:
        # Client sent bare JSON, so we send bare JSON back
        sys.stdout.buffer.write(body + b"\n")
        sys.stdout.buffer.flush()
        log.info(f"SENT (Bare JSON): {body.decode('utf-8')}")
    else:
        # Default to standard MCP Content-Length framing
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        sys.stdout.buffer.write(header + body)
        sys.stdout.buffer.flush()
        log.info(f"SENT (Framed): {body.decode('utf-8')}")

# ── Fake Database ────────────────────────────────────────────

USERS = {
    "user_001": {
        "name": "Alex Johnson", "email": "alex@example.com",
        "phone": "+1-555-0101", "dob": "1995-06-15",
        "address": "123 Crypto Lane, Web3 City",
        "kyc_status": "verified", "wallet_balance": 25.50,
        "currency": "USDT", "has_card": False,
    },
    "user_002": {
        "name": "Sam Rivera", "email": "sam@example.com",
        "phone": "+1-555-0202", "dob": "1990-03-22",
        "address": "456 DeFi Street, Block Town",
        "kyc_status": "not_started", "wallet_balance": 3.00,
        "currency": "USDT", "has_card": False,
    },
}

CARD_OFFERS = [
    {
        "offer_id": "CARD_VIRTUAL_001", "card_name": "Luffa Virtual Card",
        "card_type": "virtual", "issuance_fee": 5.00, "currency": "USDT",
        "annual_fee": 0.00, "cashback": "1%",
        "features": ["Instant issuance", "Online payments", "Web3 compatible"],
        "valid_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
    },
    {
        "offer_id": "CARD_PHYSICAL_002", "card_name": "Luffa Physical Card",
        "card_type": "physical", "issuance_fee": 15.00, "currency": "USDT",
        "annual_fee": 10.00, "cashback": "2%",
        "features": ["Physical delivery", "ATM withdrawals", "Global acceptance"],
        "valid_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
    },
]

# ── Tool Definitions ─────────────────────────────────────────

TOOLS = [
    {
        "name": "get_wallet_info",
        "description": "Get the user's Luffa wallet balance and whether they already have a card.",
        "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}
    },
    {
        "name": "get_card_offers",
        "description": "Fetch all available Luffa Card offers with issuance fees, type and features.",
        "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}
    },
    {
        "name": "check_kyc_status",
        "description": "Check if user's KYC identity verification is complete. Required before card application.",
        "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}
    },
    {
        "name": "check_sufficient_balance",
        "description": "Check if user wallet balance covers the card issuance fee. Returns shortfall amount if not.",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}, "offer_id": {"type": "string"}},
            "required": ["user_id", "offer_id"]
        }
    },
    {
        "name": "get_user_profile",
        "description": "Get user profile data to pre-fill card application. Returns list of missing fields.",
        "inputSchema": {"type": "object", "properties": {"user_id": {"type": "string"}}, "required": ["user_id"]}
    },
    {
        "name": "submit_card_application",
        "description": (
            "CRITICAL: Submit Luffa Card application and deduct fee from wallet. "
            "MUST only be called with confirmed=true after user explicitly says YES. "
            "Returns BLOCKED if confirmed=false."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "offer_id": {"type": "string"},
                "confirmed": {"type": "boolean", "description": "true ONLY after user said YES"},
                "additional_info": {"type": "object"}
            },
            "required": ["user_id", "offer_id", "confirmed"]
        }
    },
    {
        "name": "top_up_wallet",
        "description": "Add funds to the user's Luffa wallet (simulated).",
        "inputSchema": {
            "type": "object",
            "properties": {"user_id": {"type": "string"}, "amount": {"type": "number"}},
            "required": ["user_id", "amount"]
        }
    },
]

# ── Tool Implementations ─────────────────────────────────────

def get_wallet_info(user_id):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    u = USERS[user_id]
    return {"user_name": u["name"], "wallet_balance": u["wallet_balance"], "currency": u["currency"], "has_card": u["has_card"]}

def get_card_offers(user_id):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    if USERS[user_id]["has_card"]: return {"error": "User already has an active Luffa Card."}
    return {"offers": CARD_OFFERS}

def check_kyc_status(user_id):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    kyc = USERS[user_id]["kyc_status"]
    return {
        "kyc_status": kyc, "can_apply": kyc == "verified",
        "message": {"verified": "KYC complete. User can proceed.",
                    "pending": "KYC under review (24-48 hrs).",
                    "not_started": "KYC not started. Must complete identity verification."}.get(kyc)
    }

def check_sufficient_balance(user_id, offer_id):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    offer = next((o for o in CARD_OFFERS if o["offer_id"] == offer_id), None)
    if not offer: return {"error": f"Offer '{offer_id}' not found."}
    u = USERS[user_id]; bal, fee = u["wallet_balance"], offer["issuance_fee"]
    return {"current_balance": bal, "required_fee": fee, "currency": u["currency"],
            "is_sufficient": bal >= fee, "shortfall": round(max(0, fee - bal), 2),
            "requires_user_confirmation": True}

def get_user_profile(user_id):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    u = USERS[user_id]
    profile = {k: u[k] for k in ["name","email","phone","dob","address"]}
    missing = [k for k,v in profile.items() if not v]
    return {"profile": profile, "missing_fields": missing, "profile_complete": not missing}

def submit_card_application(user_id, offer_id, confirmed, additional_info=None):
    if not confirmed:
        return {"blocked": True, "message": (
            "BLOCKED. You MUST ask the user: 'Do you confirm applying for the Luffa Card? (YES/NO)' "
            "Only call this again with confirmed=true if they say YES."
        )}
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    offer = next((o for o in CARD_OFFERS if o["offer_id"] == offer_id), None)
    if not offer: return {"error": f"Offer '{offer_id}' not found."}
    u = USERS[user_id]
    if u["wallet_balance"] < offer["issuance_fee"]: return {"error": "Insufficient balance at submission."}
    if u["kyc_status"] != "verified": return {"error": f"KYC not verified: {u['kyc_status']}"}
    USERS[user_id]["wallet_balance"] = round(u["wallet_balance"] - offer["issuance_fee"], 2)
    USERS[user_id]["has_card"] = True
    expiry = (datetime.now() + timedelta(days=365*3)).strftime("%m/%Y")
    return {
        "status": "approved", "application_id": f"APP-{random.randint(100000,999999)}",
        "card_number": f"4242 **** **** {random.randint(1000,9999)}", "expiry": expiry,
        "fee_deducted": offer["issuance_fee"], "remaining_balance": USERS[user_id]["wallet_balance"],
        "next_steps": "Virtual card is ready to use immediately." if offer["card_type"]=="virtual"
                      else "Physical card will arrive in 5-7 business days."
    }

def top_up_wallet(user_id, amount):
    if user_id not in USERS: return {"error": f"User '{user_id}' not found."}
    if amount <= 0: return {"error": "Amount must be > 0."}
    USERS[user_id]["wallet_balance"] = round(USERS[user_id]["wallet_balance"] + amount, 2)
    return {"amount_added": amount, "new_balance": USERS[user_id]["wallet_balance"], "currency": USERS[user_id]["currency"]}

HANDLERS = {
    "get_wallet_info": get_wallet_info, "get_card_offers": get_card_offers,
    "check_kyc_status": check_kyc_status, "check_sufficient_balance": check_sufficient_balance,
    "get_user_profile": get_user_profile, "submit_card_application": submit_card_application,
    "top_up_wallet": top_up_wallet,
}

# ── MCP Protocol Handler ─────────────────────────────────────

def handle(msg):
    method, mid = msg.get("method"), msg.get("id")

    if method == "initialize":
        # send_message({"jsonrpc":"2.0","id":mid,"result":{
        #     "capabilities":{"tools":{}},
        #     "serverInfo":{"name":"luffa-fake-mcp","version":"1.0.0"}
        # }})
        send_message({
        "jsonrpc": "2.0",
        "id": mid,
        "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": False
                }
            },
            "serverInfo": {
                "name": "luffa-fake-mcp",
                "version": "1.0.0"
            }
            }
        })
        # ✅ REQUIRED by mcp SDK — sends this so handshake completes
        # send_message({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})

    elif method == "tools/list":
        send_message({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})

    elif method == "tools/call":
        p = msg.get("params",{}); name = p.get("name"); args = p.get("arguments",{})
        log.info(f"CALL {name}({args})")
        if name not in HANDLERS:
            send_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Unknown tool: {name}"}})
            return
        try:
            result = HANDLERS[name](**args)
        except Exception as e:
            result = {"error": str(e)}
        log.info(f"RESULT {result}")
        send_message({"jsonrpc":"2.0","id":mid,"result":{
            "content":[{"type":"text","text":json.dumps(result,indent=2)}],
            "isError": "error" in result or "blocked" in result
        }})
    elif method in ("resources/list", "prompts/list"):
        # Safely return empty lists so strict clients don't panic
        key = method.split("/")[0] # "resources" or "prompts"
        send_message({"jsonrpc": "2.0", "id": mid, "result": {key: []}})

    elif method == "ping":
        send_message({"jsonrpc":"2.0","id":mid,"result":{}})

    elif method and method.startswith("notifications/"):
        log.info(f"NOTIFICATION: {method}")

    elif mid is not None:
        send_message({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Method not found: {method}"}})

# ── Main Loop ────────────────────────────────────────────────

def main():
    log.info("Luffa Fake MCP Server started (Content-Length framing).")
    while True:
        try:
            msg = read_message()
            if msg is None:
                log.info("EOF. Shutting down.")
                break
            handle(msg)
        except json.JSONDecodeError as e:
            log.error(f"JSON error: {e}")
        except Exception as e:
            log.error(f"Error: {e}", exc_info=True)

if __name__ == "__main__":
    main()