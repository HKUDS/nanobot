---
name: crow
description: Agent payment service via CrowPay — gives your agent a wallet to pay for APIs and services. Use this skill whenever the agent needs to handle HTTP 402 Payment Required responses, pay for an API, buy credits or subscriptions, pay a merchant with a credit card, set up an agent wallet, or manage spending rules. Also use when the user mentions CrowPay, Crow, agent payments, USDC, x402, or buying anything on the internet for the agent — even if they don't say "Crow" by name.
---

# Crow — Agent Payment Service

Crow gives your AI agent a wallet to pay for APIs and services autonomously — within spending rules set by the wallet owner. All interaction is via **curl / HTTP requests** to `https://api.crowpay.ai`.

Two payment methods:
- **x402 (USDC on Base)** — for APIs that return HTTP 402 Payment Required
- **Credit card (Stripe)** — for merchants, subscriptions, API credits

**Dashboard:** https://crowpay.ai/dashboard

## When to Use This Skill

- Agent gets an HTTP `402 Payment Required` response
- Agent needs to pay for an API, buy credits, or pay a merchant
- User wants to set up an agent wallet with spending rules
- User asks about CrowPay, Crow, or agent payments
- User wants their agent to buy something on the internet

---

## Setup — Get a Wallet and API Key

```bash
curl -X POST https://api.crowpay.ai/setup \
  -H "Content-Type: application/json" \
  -d '{}'
```

Response:
```json
{
  "apiKey": "crow_sk_abc123...",
  "walletAddress": "0x1234...abcd",
  "claimUrl": "https://crowpay.ai/claim/xyz789",
  "fundingInstructions": "Send USDC on Base to 0x1234...abcd"
}
```

**Three things to do after setup:**
1. **Save the `apiKey` immediately** — it is shown only once and cannot be retrieved later
2. Tell the user to visit the `claimUrl` to create their account and set spending rules
3. Fund the wallet: send USDC on Base to `walletAddress`, or add a credit card in the dashboard

All subsequent requests need this header:
```
X-API-Key: crow_sk_abc123...
```

---

## Decision Tree

```
Agent needs to pay for something?
│
├── Got an HTTP 402 from an API? (x402 / USDC)
│   │
│   └── curl POST /authorize  ← pass the full 402 response body
│       ├── 200 → Got signed payload. Retry original request with payment-signature header.
│       ├── 202 → Needs human approval. Poll GET /authorize/status every 3s.
│       └── 403 → Spending rules blocked it. Tell the user.
│
└── Paying a merchant with credit card?
    │
    └── curl POST /authorize/card  ← pass amount, merchant, reason
        ├── 200 → Got sptToken. Use it to pay via Stripe.
        ├── 202 → Needs human approval. Poll GET /authorize/status every 3s.
        └── 403 → Spending rules blocked it. Tell the user.
```

---

## Endpoints

### POST /setup — Create wallet + API key

No auth required.

```bash
curl -X POST https://api.crowpay.ai/setup \
  -H "Content-Type: application/json" \
  -d '{"network": "eip155:8453"}'
```

`network` is optional (defaults to Base mainnet). Response contains `apiKey`, `walletAddress`, `claimUrl`.

---

### POST /authorize — Pay for an x402 API (USDC)

When you hit an API and get a `402 Payment Required` response, forward the entire response body to Crow:

```bash
curl -X POST https://api.crowpay.ai/authorize \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "paymentRequired": {
      "x402Version": 2,
      "resource": {"url": "https://api.example.com/v1/data"},
      "accepts": [{
        "scheme": "exact",
        "network": "eip155:8453",
        "amount": "1000000",
        "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "payTo": "0xRecipientAddress",
        "maxTimeoutSeconds": 60,
        "extra": {"name": "USDC", "version": "2"}
      }]
    },
    "merchant": "ExampleAPI",
    "reason": "Fetching data for user task",
    "platform": "Claude MCP",
    "service": "Premium data API"
  }'
```

**Required fields:**
- `paymentRequired` — the full 402 response body from the API
- `merchant` — name of the service (wallet owner sees this)
- `reason` — why the payment is needed (wallet owner sees this)

**Optional context fields (recommended):**
- `platform` — which agent/platform is making the request (e.g. "Claude MCP", "LangChain")
- `service` — what service/product the payment is for (e.g. "Weather API call", "Premium data")

**200 → Auto-approved.** Response is a signed payment payload. To retry the original request:
```bash
# Base64-encode the entire response and put it in the payment-signature header
PAYMENT=$(echo '<full JSON response>' | base64)
curl https://api.example.com/v1/data -H "payment-signature: $PAYMENT"
```

**202 → Needs human approval.** Response contains `approvalId`. Poll for status (see below).

**403 → Denied.** Spending rules blocked it. Do not retry with same params.

See `references/x402-flow.md` for the complete end-to-end walkthrough.

---

### POST /authorize/card — Pay a merchant with credit card

```bash
curl -X POST https://api.crowpay.ai/authorize/card \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "amountCents": 1000,
    "merchant": "OpenAI",
    "reason": "GPT-4 API credits",
    "platform": "Claude MCP",
    "service": "GPT-4 API credits"
  }'
```

**Required fields:**
- `amountCents` — amount in cents (`1000` = $10.00)
- `merchant` — merchant name
- `reason` — why the payment is needed

**Optional fields:**
- `currency` — defaults to `"usd"`
- `paymentMethodId` — specific card to use (uses default card if omitted)
- `merchantStripeAccount` — Stripe Connect account ID if applicable
- `platform` — which agent/platform is making the request (e.g. "Claude MCP", "LangChain")
- `service` — what service/product the payment is for (e.g. "GPT-4 credits", "API subscription")

**200 → Auto-approved:**
```json
{"approved": true, "sptToken": "spt_...", "transactionId": "..."}
```
Use the `sptToken` to pay the merchant. Expires in 1 hour.

**202 → Needs human approval.** Poll for status.

**403 → Denied.** Spending rules blocked it.

See `references/card-payments.md` for full details.

---

### GET /authorize/status — Poll for approval

```bash
curl "https://api.crowpay.ai/authorize/status?id=APPROVAL_ID" \
  -H "X-API-Key: crow_sk_abc123..."
```

Poll every **3 seconds**. Do not poll faster.

| Status in response | What to do |
|--------------------|------------|
| `"pending"` | Keep polling |
| `"signing"` | Keep polling (approved, generating payload) |
| Response has `payload` field | Done — use the signed payload to pay |
| Response has `sptToken` field | Done — use token for card payment |
| `"denied"` | Stop. Owner rejected the payment. |
| `"timeout"` | Stop. Approval window expired. |
| `"failed"` | Stop. Error during signing. |

---

### POST /settle — Report x402 settlement

After the x402 facilitator settles your payment on-chain, report it. Idempotent — safe to call multiple times.

```bash
curl -X POST https://api.crowpay.ai/settle \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{"transactionId": "...", "txHash": "0x..."}'
```

Not needed for card payments (Stripe webhooks handle this automatically).

---

## Key Numbers

| Type | Format | Example | Dollar value |
|------|--------|---------|-------------|
| USDC (x402) | Atomic units, 6 decimals | `1000000` | $1.00 |
| USDC (x402) | Atomic units, 6 decimals | `100000` | $0.10 |
| Card | Cents | `100` | $1.00 |
| Card | Cents | `1000` | $10.00 |

- **Network:** Base mainnet (`eip155:8453`)
- **USDC contract:** `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913`

## Default Spending Rules

Auto-created when wallet is claimed:
- Per-transaction limit: **$25**
- Daily limit: **$50**
- Auto-approve threshold: **$5** (above this → human must approve)

Owners customize these in the dashboard.

## References

For deeper walkthroughs with complete curl examples and all edge cases:

- `references/api-reference.md` — Complete API reference: every endpoint, every field, every response code with curl examples
- `references/x402-flow.md` — End-to-end 402 payment walkthrough with curl
- `references/card-payments.md` — Credit card payment walkthrough with curl
- `references/error-handling.md` — All error codes, retry strategy, polling best practices

## Finding Services to Pay For

Use [Nightmarket](https://nightmarket.ai) to discover paid APIs your agent can call. Every Nightmarket service uses x402 — Crow handles the payments automatically.

Install the Nightmarket skill:
```
npx skills add https://github.com/Fallomai/skills --skill nightmarket
```
