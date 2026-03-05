# Credit Card Payments — End-to-End with curl

Pay merchants with a credit card using Stripe Shared Payment Tokens (SPTs). Use this when there's no 402 involved — e.g., paying for SaaS, API credits, subscriptions.

## Prerequisites

- Wallet must be claimed (user visited `claimUrl` from `/setup`)
- A credit card must be added in the dashboard at https://crowpay.ai/dashboard
- Card spending rules are auto-created when a card is added

## Step 1: Request a card payment

```bash
curl -X POST https://api.crowpay.ai/authorize/card \
  -H "X-API-Key: crow_sk_abc123..." \
  -H "Content-Type: application/json" \
  -d '{
    "amountCents": 500,
    "merchant": "OpenAI",
    "reason": "GPT-4 API credits for code review task",
    "platform": "Claude MCP",
    "service": "GPT-4 API credits"
  }'
```

### All request fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `amountCents` | integer | Yes | — | Amount in cents. `500` = $5.00. Must be positive. |
| `merchant` | string | Yes | — | Merchant name (wallet owner sees this) |
| `reason` | string | Yes | — | Why the payment is needed (wallet owner sees this) |
| `currency` | string | No | `"usd"` | Currency code |
| `paymentMethodId` | string | No | default card | ID of a specific card to charge |
| `merchantStripeAccount` | string | No | — | Stripe Connect account ID if applicable |
| `platform` | string | No | — | Which agent/platform is making the request (e.g. "Claude MCP") |
| `service` | string | No | — | What service/product the payment is for (e.g. "GPT-4 credits") |

## Step 2a: If 200 — Auto-approved

Amount is within the auto-approve threshold (default $5):

```json
{
  "approved": true,
  "sptToken": "spt_abc123def456...",
  "transactionId": "txn_xyz789"
}
```

The `sptToken` is a Stripe Shared Payment Token. Use it to pay the merchant through Stripe's payment API. The token expires in **1 hour**.

## Step 2b: If 202 — Needs human approval

Amount exceeds auto-approve threshold:

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
curl "https://api.crowpay.ai/authorize/status?id=approval_abc123" \
  -H "X-API-Key: crow_sk_abc123..."
```

When approved, response will contain `sptToken`:

```json
{
  "approved": true,
  "sptToken": "spt_abc123def456...",
  "transactionId": "txn_xyz789"
}
```

If `"denied"`, `"timeout"`, or `"failed"` — stop and inform the user.

## Step 2c: If 403 — Denied

Spending rules blocked the payment:

```json
{
  "error": "Payment denied",
  "reason": "Exceeds daily limit of $50.00"
}
```

Do not retry with same params. Tell the user.

## Default card spending rules

Created automatically when a card is added:

| Rule | Default |
|------|---------|
| Daily limit | $50 (5000 cents) |
| Per-transaction limit | $25 (2500 cents) |
| Auto-approve threshold | $5 (500 cents) |

Owners can customize all limits in the dashboard under the "Rules" tab.

## Settlement

Card payments are tracked automatically via Stripe webhooks — no need to call `/settle`.

- `shared_payment.issued_token.used` → transaction marked as settled
- `shared_payment.issued_token.deactivated` → transaction marked as failed

## Common errors

| Error | Cause | Fix |
|-------|-------|-----|
| `amountCents must be a positive integer` | Invalid amount | Use a positive integer in cents |
| `Missing required fields: merchant, reason` | Body incomplete | Add both fields |
| `No payment methods configured` | No card added | User needs to add card in dashboard |
| `Payment method not found or not owned by you` | Bad `paymentMethodId` | Omit it to use default card |
