# Nightmarket + CrowPay Integration

Use CrowPay to handle Nightmarket payments automatically — no wallet private key needed.

## How It Works

Nightmarket services use the x402 protocol (HTTP 402). CrowPay already knows how to handle 402s. When combined:

1. Your agent calls the Nightmarket proxy URL
2. Gets `402 Payment Required` with a `PAYMENT-REQUIRED` header
3. Forwards the 402 to Crow's `/authorize` endpoint
4. Crow checks spending rules and signs the payment
5. Agent retries with the `payment-signature` header
6. Done — no private key exposure

## Step-by-Step Flow

### 1. Call the Nightmarket proxy

```
POST https://nightmarket.ai/api/x402/<endpoint_id>
Content-Type: application/json

<request body>
```

### 2. Forward the 402 to Crow

```
POST https://api.crowpay.ai/authorize
X-API-Key: crow_sk_...
Content-Type: application/json

{
  "paymentRequired": <the full 402 response body>,
  "merchant": "Nightmarket — <service name>",
  "reason": "API call to <service name>"
}
```

### 3. Handle Crow's response

- **200 — Approved**: Retry original request with `payment-signature: <base64(JSON.stringify(response_body))>`
- **202 — Pending**: Poll `/authorize/status?id=<approvalId>` every 3 seconds for human approval
- **403 — Denied**: Spending rules blocked it, do not retry

### 4. After successful payment

Report settlement back to Crow:

```
POST https://api.crowpay.ai/settle
X-API-Key: crow_sk_...
Content-Type: application/json

{
  "transactionId": "...",
  "txHash": "0x..."
}
```

## Why Use CrowPay

- No private key in config files
- Spending rules and limits
- Human approval for large amounts
- Audit trail of all payments
- One wallet across Nightmarket and other x402 services
