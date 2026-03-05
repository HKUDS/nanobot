# x402 Payment Flow — End-to-End with curl

Step-by-step guide for handling HTTP 402 Payment Required responses using Crow.

## Overview

x402 is a protocol where APIs return HTTP 402 with payment details. You forward the 402 body to Crow, Crow checks spending rules and signs a USDC authorization, and you retry the original request with the signed payment.

## Step 1: Call an API and get a 402

```bash
curl -i https://api.example.com/v1/data
```

Response:
```
HTTP/1.1 402 Payment Required
Content-Type: application/json

{
  "x402Version": 2,
  "resource": {"url": "https://api.example.com/v1/data", "description": "Premium data"},
  "accepts": [{
    "scheme": "exact",
    "network": "eip155:8453",
    "amount": "500000",
    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
    "payTo": "0xMerchantAddress",
    "maxTimeoutSeconds": 60,
    "extra": {"name": "USDC", "version": "2"}
  }]
}
```

This means: "Pay $0.50 USDC on Base to access this endpoint."

## Step 2: Forward the 402 to Crow

Pass the **entire 402 response body** as `paymentRequired`, and add a clear `merchant` name and `reason`:

```bash
curl -X POST https://api.crowpay.ai/authorize \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "paymentRequired": {
      "x402Version": 2,
      "resource": {"url": "https://api.example.com/v1/data", "description": "Premium data"},
      "accepts": [{
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "500000",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "payTo": "0xMerchantAddress",
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2"}
      }]
    },
    "merchant": "ExampleAPI",
    "reason": "Fetching premium data for user analysis",
    "platform": "Claude MCP",
    "service": "Premium data API"
  }'
```

The wallet owner sees the `merchant` and `reason` when approving, so make them descriptive.

## Step 3a: If 200 — Auto-approved

Crow checked spending rules and $0.50 is within the auto-approve threshold. You get a signed payment payload:

```json
{
  "x402Version": 2,
  "resource": {"url": "https://api.example.com/v1/data"},
  "accepted": {"scheme": "exact", "network": "eip155:8453", "amount": "500000", "...": "..."},
  "payload": {
    "signature": "0xabc123...",
    "authorization": {
      "from": "0xYourWallet",
      "to": "0xMerchantAddress",
      "value": "500000",
      "validAfter": "1740672089",
      "validBefore": "1740672154",
      "nonce": "0xrandomnonce..."
    }
  }
}
```

Retry your original request with this payload base64-encoded in the `payment-signature` header:

```bash
# Save the full Crow response to a variable
CROW_RESPONSE='{"x402Version":2,"resource":{"url":"https://api.example.com/v1/data"},"accepted":{...},"payload":{...}}'

# Base64-encode it
PAYMENT=$(echo -n "$CROW_RESPONSE" | base64 -w0)

# Retry the original request
curl https://api.example.com/v1/data \
  -H "payment-signature: $PAYMENT"
```

The x402 facilitator on the API side verifies the signature and settles the USDC transfer on-chain.

## Step 3b: If 202 — Needs human approval

The amount exceeds the auto-approve threshold. The wallet owner gets a notification and must approve in their dashboard.

```json
{
  "status": "pending",
  "approvalId": "approval_abc123",
  "expiresAt": 1740672200,
  "message": "Payment requires human approval. Poll GET /authorize/status?id=approval_abc123"
}
```

Poll every 3 seconds:

```bash
# Poll for status
curl "https://api.crowpay.ai/authorize/status?id=approval_abc123" \
  -H "X-API-Key: crow_sk_abc123..."
```

Keep polling while status is `"pending"` or `"signing"`.

When the response contains a `payload` field, use it the same way as step 3a — base64-encode and retry.

If status is `"denied"`, `"timeout"`, or `"failed"` — stop. The payment was not approved.

## Step 3c: If 403 — Denied

Spending rules blocked this payment. The response tells you why:

```json
{
  "error": "Payment denied",
  "reason": "Exceeds per-transaction limit of $25.00"
}
```

Do **not** retry with the same parameters. Tell the user.

## Step 4: Report settlement

After the x402 facilitator settles the payment on-chain:

```bash
curl -X POST https://api.crowpay.ai/settle \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "transactionId": "txn_xyz789",
    "txHash": "0xabcdef1234567890..."
  }'
```

This is idempotent — safe to call multiple times.

## Key details

- USDC amounts are in **atomic units** with 6 decimals: `1000000` = $1.00, `500000` = $0.50
- Network is always Base mainnet: `eip155:8453`
- USDC contract: `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`
- Crow signs EIP-3009 `TransferWithAuthorization` — the facilitator settles on-chain
- The wallet's private key never leaves Crow's server
- Default auto-approve threshold is $5 — owner can change this in dashboard
