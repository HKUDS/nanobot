# Error Handling

All Crow API errors return JSON:

```json
{
  "error": "Short error message",
  "reason": "Detailed explanation (on 403s)",
  "details": "Technical details (on 500s)"
}
```

## Status Codes

| Status | Meaning | Retry? | Action |
|--------|---------|--------|--------|
| 200 | Success | — | Proceed |
| 202 | Pending approval | Poll | Poll `/authorize/status` every 3s |
| 400 | Bad request | No | Fix the request |
| 401 | Unauthorized | No | Check API key |
| 403 | Denied by rules | No | Inform user, do not retry same params |
| 404 | Not found | No | Check the ID |
| 422 | Invalid state | No | Transaction is in wrong state |
| 429 | Rate limited | Yes | Wait, then retry with backoff |
| 500 | Server error | Yes | Retry with exponential backoff |

## Errors by Endpoint

### POST /setup

| Error | Cause |
|-------|-------|
| 429 `Rate limit exceeded` | Too many setup calls from this IP |

### POST /authorize

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `Missing required fields: paymentRequired, merchant, reason` | Request body incomplete |
| 400 | `No compatible payment option` | Wallet doesn't support requested network/asset |
| 401 | `Missing X-API-Key header` | No API key provided |
| 401 | `Invalid API key or wallet not found` | Key is wrong or revoked |
| 401 | `Wallet not claimed` | User hasn't visited the claim URL |
| 403 | `Payment denied` | Spending rules blocked it (check `reason` field) |

### POST /authorize/card

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `amountCents must be a positive integer` | Invalid amount |
| 400 | `Missing required fields: merchant, reason` | Request body incomplete |
| 400 | `No payment methods configured` | No card in dashboard |
| 403 | `Payment denied` | Spending rules blocked it (check `reason` field) |
| 403 | `Payment method not found or not owned by you` | Bad `paymentMethodId` |

### GET /authorize/status

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `Missing id query parameter` | No `?id=` in URL |
| 403 | `Forbidden` | Approval belongs to a different wallet |
| 404 | `Approval not found` | Invalid approval ID |

### POST /settle

| Status | Error | Cause |
|--------|-------|-------|
| 400 | `Missing transactionId or txHash` | Request body incomplete |
| 403 | `Forbidden` | Transaction belongs to a different wallet |
| 404 | `Transaction not found` | Invalid transaction ID |
| 422 | `Cannot settle transaction with status: ...` | Wrong state (e.g., still pending approval) |

## Retry Strategy

For retryable errors (429, 5xx), use exponential backoff:

```bash
# Simple retry with backoff
for i in 1 2 3; do
  response=$(curl -s -w "\n%{http_code}" -X POST https://api.crowpay.ai/authorize \
    -H "X-API-Key: crow_sk_..." \
    -H "Content-Type: application/json" \
    -d '...')

  status_code=$(echo "$response" | tail -1)
  body=$(echo "$response" | head -1)

  if [ "$status_code" -lt 500 ] && [ "$status_code" -ne 429 ]; then
    echo "$body"
    break
  fi

  sleep $((i * 2))
done
```

## Polling Best Practices

When polling `/authorize/status`:
- Poll every **3 seconds** — not faster
- Set a max timeout (e.g., 5 minutes) to avoid infinite loops
- The `expiresAt` timestamp in the 202 response tells you when the approval window closes
- Handle all terminal states: `denied`, `timeout`, `failed`

```bash
# Poll loop
APPROVAL_ID="abc123"
MAX_ATTEMPTS=100  # 5 minutes at 3s intervals

for i in $(seq 1 $MAX_ATTEMPTS); do
  response=$(curl -s "https://api.crowpay.ai/authorize/status?id=$APPROVAL_ID" \
    -H "X-API-Key: crow_sk_...")

  status=$(echo "$response" | jq -r '.status // empty')

  # Check for signed payload (x402)
  if echo "$response" | jq -e '.payload' > /dev/null 2>&1; then
    echo "Approved! Got payment payload."
    echo "$response"
    break
  fi

  # Check for SPT token (card)
  if echo "$response" | jq -e '.sptToken' > /dev/null 2>&1; then
    echo "Approved! Got SPT token."
    echo "$response"
    break
  fi

  # Terminal states
  case "$status" in
    denied|timeout|failed)
      echo "Payment $status: $(echo "$response" | jq -r '.reason')"
      break
      ;;
    pending|signing)
      sleep 3
      ;;
  esac
done
```

## Constants

| Constant | Value |
|----------|-------|
| USDC contract (Base) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` |
| Network (CAIP-2) | `eip155:8453` |
| USDC decimals | 6 |
| $1.00 in USDC atomic units | `1000000` |
| $1.00 in card cents | `100` |
