# Nightmarket API Reference

Everything is standard HTTP. No SDK, no special client — just curl.

## Search & Discovery

### List / search services

```
GET https://nightmarket.ai/api/marketplace
GET https://nightmarket.ai/api/marketplace?search=<query>
GET https://nightmarket.ai/api/marketplace?sort=<sort>
GET https://nightmarket.ai/api/marketplace?search=<query>&sort=<sort>
```

**Query parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `search` | string | — | Filter by name, description, or seller (case-insensitive) |
| `sort` | string | `popular` | One of: `popular`, `newest`, `price_asc`, `price_desc` |

**Response:** JSON array of services

```json
[
  {
    "_id": "abc123def456",
    "name": "Weather Forecast API",
    "description": "Get current weather and 7-day forecasts",
    "method": "GET",
    "priceUsdc": 0.01,
    "totalCalls": 1247,
    "totalRevenue": 12.47,
    "seller": {
      "companyName": "WeatherCo",
      "description": "Weather data provider"
    }
  }
]
```

### Get service details

```
GET https://nightmarket.ai/api/marketplace/<endpoint_id>
```

**Response:** single service object with the same fields as above, plus:

```json
{
  "requestExample": "?city=NYC",
  "responseExample": "{\"temp\": 72, \"forecast\": [...]}",
  "sellerId": "seller789"
}
```

Returns 404 if the endpoint doesn't exist or is inactive.

---

## Calling Services

### Proxy URL

```
<METHOD> https://nightmarket.ai/api/x402/<endpoint_id>
```

- `METHOD`: GET, POST, PUT, PATCH, or DELETE (must match what the service expects)
- `endpoint_id`: the service's `_id` from the search response

### Request Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Content-Type` | For POST/PUT/PATCH | Usually `application/json` |
| `Authorization` | If service requires it | Passed through to the seller's API |
| `payment-signature` | After 402 | Signed x402 payment proof |

### Request Body

Pass the body exactly as the service expects it. The proxy forwards it unchanged.

---

## Payment Flow

### First call → 402 Payment Required

Every first call returns 402. This is normal — it's how x402 works.

**Response headers:**
- `PAYMENT-REQUIRED`: encoded payment requirements containing:
  - `scheme`: "exact"
  - `payTo`: seller's payment address (on Base)
  - `price`: amount in USDC (e.g., "$0.01")
  - `network`: "base"

**Response body:** `{}`

### Retry with payment → Success

Resend the exact same request with the payment proof.

**Add this header:**
- `payment-signature`: your signed x402 payment proof

**Successful response headers:**
- `PAYMENT-RESPONSE`: settlement proof containing `txHash` (on-chain transaction hash)

**Successful response body:** the seller's API response, passed through unchanged.

---

## Error Codes

| Status | Meaning | Action |
|--------|---------|--------|
| 200-299 | Success | Response body is the API result |
| 400 | Invalid endpoint ID or bad payment signature | Check your endpoint_id and payment format |
| 402 | Payment required | Normal — sign payment and retry |
| 402 (after payment) | Payment verification or settlement failed | Check wallet balance, verify signature |
| 403 | Endpoint URL blocked | Internal safety check — seller's URL not allowed |
| 404 | Endpoint not found or inactive | Service may have been removed |
| 502 | Seller's API unreachable | The seller's backend is down — try later |
| 503 | Seller payment not configured | Seller hasn't set up their payout wallet |

---

## Complete Examples

### Search → Get details → Call

```bash
# Search for weather APIs
curl "https://nightmarket.ai/api/marketplace?search=weather"

# Get full details for one
curl "https://nightmarket.ai/api/marketplace/abc123"

# Call it (first attempt — will get 402)
curl -i -X GET "https://nightmarket.ai/api/x402/abc123?city=NYC"
# HTTP/1.1 402 Payment Required
# PAYMENT-REQUIRED: <encoded payment details>

# Call it again with payment
curl -X GET "https://nightmarket.ai/api/x402/abc123?city=NYC" \
  -H "payment-signature: <signed payment>"
# HTTP/1.1 200 OK
# PAYMENT-RESPONSE: <settlement proof>
# {"temp": 72, "conditions": "sunny", "forecast": [...]}
```

### POST request with body

```bash
curl -i -X POST "https://nightmarket.ai/api/x402/def456" \
  -H "Content-Type: application/json" \
  -d '{"text": "I love this product"}'
# HTTP/1.1 402 Payment Required

curl -X POST "https://nightmarket.ai/api/x402/def456" \
  -H "Content-Type: application/json" \
  -H "payment-signature: <signed payment>" \
  -d '{"text": "I love this product"}'
# HTTP/1.1 200 OK
# {"sentiment": "positive", "confidence": 0.95}
```

## Rate Limits & Timeouts

- **Proxy timeout:** 30 seconds per request
- **No rate limits** from Nightmarket (individual sellers may have their own)
- **Payment:** each call is independent — no sessions or tokens to manage
