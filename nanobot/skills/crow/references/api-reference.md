# Crow API Reference

Complete reference for all Crow endpoints. Base URL: `https://api.crowpay.ai`

## Authentication

All endpoints except `POST /setup` require:
```
X-API-Key: crow_sk_...
```

---

## POST /setup

Create a new agent wallet and API key.

```bash
curl -X POST https://api.crowpay.ai/setup \
  -H "Content-Type: application/json" \
  -d '{}'
```

### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `network` | string | No | CAIP-2 network ID. Defaults to `"eip155:8453"` (Base mainnet) |

### Responses

**200 OK**
```json
{
  "apiKey": "crow_sk_abc123def456...",
  "walletAddress": "0x1234567890abcdef1234567890abcdef12345678",
  "claimUrl": "https://crowpay.ai/claim/xyz789",
  "fundingInstructions": "Send USDC on Base to 0x1234..."
}
```

**429 Too Many Requests** — IP-based rate limit. Wait and retry.

---

## POST /authorize

Check spending rules and sign an EIP-3009 USDC payment authorization for x402 protocol.

```bash
curl -X POST https://api.crowpay.ai/authorize \
  -H "X-API-Key: crow_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "paymentRequired": {"x402Version":2,"resource":{"url":"..."},"accepts":[{"scheme":"exact","network":"eip155:8453","amount":"1000000","asset":"0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913","payTo":"0x...","maxTimeoutSeconds":60,"extra":{"name":"USDC","version":"2"}}]},
    "merchant": "ServiceName",
    "reason": "Why this payment is needed"
  }'
```

### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `paymentRequired` | object | Yes | The full HTTP 402 response body from the x402 API |
| `merchant` | string | Yes | Human-readable name of the service. Wallet owner sees this. |
| `reason` | string | Yes | Why the payment is needed. Wallet owner sees this. |
| `walletAddress` | string | No | Specific wallet to use. Defaults to API key's wallet. |
| `platform` | string | No | Which agent/platform is making the request (e.g. "Claude MCP", "LangChain"). Wallet owner sees this. |
| `service` | string | No | What service/product the payment is for (e.g. "Weather API", "Premium data"). Wallet owner sees this. |

### paymentRequired format

This is the standard x402 v2 PaymentRequired object:

```json
{
  "x402Version": 2,
  "resource": {
    "url": "https://api.example.com/v1/endpoint",
    "description": "Optional description"
  },
  "accepts": [
    {
      "scheme": "exact",
      "network": "eip155:8453",
      "amount": "1000000",
      "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
      "payTo": "0xRecipientAddress",
      "maxTimeoutSeconds": 60,
      "extra": {
        "name": "USDC",
        "version": "2"
      }
    }
  ]
}
```

### Responses

**200 OK — Auto-approved**

The signed payment payload. Use this to retry the original request.

```json
{
  "x402Version": 2,
  "resource": {"url": "https://api.example.com/v1/endpoint"},
  "accepted": {
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "1000000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payTo": "0xRecipientAddress",
    "maxTimeoutSeconds": 60,
    "extra": {"name": "USDC", "version": "2"}
  },
  "payload": {
    "signature": "0xabc123...",
    "authorization": {
      "from": "0xYourWallet",
      "to": "0xRecipient",
      "value": "1000000",
      "validAfter": "1740672089",
      "validBefore": "1740672154",
      "nonce": "0xrandomnonce..."
    }
  }
}
```

To retry the original request with payment:
```bash
PAYMENT=$(echo '{"x402Version":2,...}' | base64 -w0)
curl https://api.example.com/v1/endpoint \
  -H "payment-signature: $PAYMENT"
```

**202 Accepted — Pending human approval**
```json
{
  "status": "pending",
  "approvalId": "abc123",
  "expiresAt": 1740672200,
  "message": "Payment requires human approval. Poll GET /authorize/status?id=abc123"
}
```

**400 Bad Request**
- `Missing required fields: paymentRequired, merchant, reason`
- `No compatible payment option` — wallet doesn't support the requested network/asset

**401 Unauthorized**
- `Missing X-API-Key header`
- `Invalid API key or wallet not found`
- `Wallet not claimed — claim your wallet first`

**403 Forbidden**
- `Payment denied` with `reason` field explaining why (e.g., "Exceeds per-transaction limit of $25.00")

### Spending rules checked

1. Per-transaction limit
2. Merchant blacklist
3. Merchant whitelist (if configured)
4. Daily spending limit
5. Auto-approve threshold (above threshold → 202 pending)

---

## POST /authorize/card

Request a credit card payment. Returns a Stripe Shared Payment Token.

```bash
curl -X POST https://api.crowpay.ai/authorize/card \
  -H "X-API-Key: crow_sk_..." \
  -H "Content-Type: application/json" \
  -d '{
    "amountCents": 1000,
    "merchant": "OpenAI",
    "reason": "GPT-4 API credits"
  }'
```

### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `amountCents` | integer | Yes | Amount in cents. `1000` = $10.00. Must be positive. |
| `merchant` | string | Yes | Merchant name. Wallet owner sees this. |
| `reason` | string | Yes | Why the payment is needed. Wallet owner sees this. |
| `currency` | string | No | Defaults to `"usd"` |
| `paymentMethodId` | string | No | Specific card ID. Uses default card if omitted. |
| `merchantStripeAccount` | string | No | Stripe Connect account ID if applicable |
| `platform` | string | No | Which agent/platform is making the request (e.g. "Claude MCP", "LangChain"). Wallet owner sees this. |
| `service` | string | No | What service/product the payment is for (e.g. "GPT-4 credits", "API subscription"). Wallet owner sees this. |

### Responses

**200 OK — Auto-approved**
```json
{
  "approved": true,
  "sptToken": "spt_abc123...",
  "transactionId": "txn_xyz789"
}
```

The `sptToken` is a Stripe Shared Payment Token. Use it to pay the merchant via Stripe. Expires in 1 hour.

**202 Accepted — Pending human approval**
```json
{
  "status": "pending",
  "approvalId": "abc123",
  "expiresAt": 1740672200,
  "message": "Payment requires human approval. Poll GET /authorize/status?id=abc123"
}
```

**400 Bad Request**
- `amountCents must be a positive integer`
- `Missing required fields: merchant, reason`
- `No payment methods configured. Add a card first.`

**401 Unauthorized** — Invalid or missing API key.

**403 Forbidden**
- `Payment denied` with reason
- `Payment method not found or not owned by you`

### Default card spending rules

Created automatically when a card is added:

| Rule | Default |
|------|---------|
| Daily limit | $50 |
| Per-transaction limit | $25 |
| Auto-approve threshold | $5 |

---

## GET /authorize/status

Poll for the status of a pending approval (works for both x402 and card payments).

```bash
curl "https://api.crowpay.ai/authorize/status?id=APPROVAL_ID" \
  -H "X-API-Key: crow_sk_..."
```

### Query parameters

| Param | Required | Description |
|-------|----------|-------------|
| `id` | Yes | The `approvalId` from a 202 response |

Poll every **3 seconds**. Do not poll faster.

### Responses

**Still pending:**
```json
{"status": "pending"}
```

**Approved — signing in progress:**
```json
{"status": "signing"}
```

**Approved — x402 payload ready:**
```json
{
  "x402Version": 2,
  "resource": {"url": "..."},
  "accepted": {"scheme": "exact", "...": "..."},
  "payload": {
    "signature": "0x...",
    "authorization": {"from": "0x...", "to": "0x...", "value": "1000000", "...": "..."}
  }
}
```

**Approved — card token ready:**
```json
{
  "approved": true,
  "sptToken": "spt_...",
  "transactionId": "..."
}
```

**Denied:**
```json
{"status": "denied", "reason": "Denied by wallet owner"}
```

**Timed out:**
```json
{"status": "timeout", "reason": "Approval window expired"}
```

**Failed:**
```json
{"status": "failed", "reason": "Payment provisioning failed"}
```

**400** — Missing `id` query parameter.
**403** — Approval belongs to a different wallet.
**404** — Approval not found.

---

## POST /settle

Report that an x402 payment settled on-chain. Idempotent — safe to call multiple times.

```bash
curl -X POST https://api.crowpay.ai/settle \
  -H "X-API-Key: crow_sk_..." \
  -H "Content-Type: application/json" \
  -d '{"transactionId": "txn_xyz789", "txHash": "0xabcdef..."}'
```

### Request body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `transactionId` | string | Yes | Transaction ID from the authorize response |
| `txHash` | string | Yes | On-chain transaction hash |

### Responses

**200 OK**
```json
{"success": true}
```

Or if already settled:
```json
{"success": true, "alreadySettled": true}
```

**400** — Missing `transactionId` or `txHash`.
**403** — Transaction belongs to a different wallet.
**404** — Transaction not found.
**422** — Transaction is in wrong state (e.g., still pending approval).

Not needed for card payments — Stripe webhooks handle settlement automatically.

---

## CORS

All endpoints (except `/stripe/webhook`) support CORS with `Access-Control-Allow-Origin: *`. OPTIONS preflight requests return 204.

## Constants

| Constant | Value |
|----------|-------|
| Base URL | `https://api.crowpay.ai` |
| USDC contract (Base mainnet) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Network (CAIP-2) | `eip155:8453` |
| USDC decimals | 6 |
| $1.00 in USDC atomic units | `1000000` |
| $1.00 in card cents | `100` |
