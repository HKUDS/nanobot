---
name: packlink
description: Create and manage Packlink Pro shipments for Foolish e-commerce orders.
always: true
---

# Packlink Pro — Shipping

Manage shipments for Alessandro's e-commerce directly via Packlink Pro API.

## Sender (pre-configured)

- **Name**: Alessandro Boscarato
- **Address**: Via Chivasso 36, 14022 Castelnuovo Don Bosco (IT)
- **Phone**: +39 3500016724
- **Email**: shipping.foolish.manager@agentmail.to

---

## Standard Workflow

### 1. Get a quote

```
packlink_quote(
  to_country="IT",
  to_zip="20121",
  weight=0.5,
  width=20, height=10, length=30
)
```

Returns available carriers sorted by price with their `service_id`.

### 2. Create the shipment

```
packlink_ship(
  service_id=12345,
  collection_date="2026/05/28",
  to_name="Mario",
  to_surname="Rossi",
  to_street="Via Roma 1",
  to_city="Milano",
  to_zip="20121",
  to_country="IT",
  to_phone="+39 3331234567",
  to_email="mario@example.com",
  weight=0.5,
  width=20, height=10, length=30,
  content="Abbigliamento",
  content_value=59.90,
  order_reference="ORD-001"
)
```

Returns the Packlink reference (e.g. `IT2026PRO0001234567`).

### 3. Get the label

```
packlink_label(reference="IT2026PRO0001234567")
```

Returns the PDF URL to print and attach to the package.

### 4. Track a shipment and close the loop

After `packlink_ship` succeeds, **always** do these three things before considering the order handled:

```
# 4a — get carrier tracking number
packlink_track(reference="IT2026PRO0001234567")
# → returns carrier tracking number and URL (e.g. BRT 179032133107784)

# 4b — update tracking-log.md
# Add the "Tracking:" field and the carrier URL to the shipment entry.

# 4c — update CMS order
PATCH /api/orders/<id>
  pipelineState = "shipped"
  trackingNumber = <carrier tracking number from packlink_track>
```

Skipping 4b/4c means the cron will see the CMS order as still open and alert Alessandro unnecessarily.

---

## How Alessandro gives shipping instructions (via Telegram)

Alessandro will typically say something like:
> "Crea spedizione per Mario Rossi, Via Roma 1, Milano 20121, pacco 0.5kg 20x10x30, ordine ORD-001, valore 59.90€"

**When this happens:**
1. Run `packlink_quote` to find the cheapest available service
2. Show Alessandro the top 3 options with price and transit time
3. Ask which carrier to use (or use the cheapest if he says "il più economico")
4. Run `packlink_ship` with the chosen service
5. Run `packlink_label` and return the label URL

**Default collection date**: use the next working day (`first_collection_date` from quote results).

---

## Notes

- `content_value` is the declared value for insurance — use the actual order value
- `content` field: use a generic description like "Abbigliamento", "Accessori", "Prodotti artigianali"
- If the destination is outside Italy, always confirm customs requirements before proceeding
- For drop-off services (InPost, etc.) remind Alessandro to bring the package to the parcel point

## Tracking customers

`packlink_track` returns:
- **Status** (e.g. `IN_TRANSIT`)
- **Carrier tracking number** (e.g. BRT `179032133107784`)
- **Carrier tracking URL** — already built and ready to send (e.g. `https://vas.brt.it/vas/sped_det_show.hsm?chisono=179032133107784`)
- **Estimated delivery date**

Use the **carrier tracking URL** in all customer communications. Never ask Alessandro for tracking links — `packlink_track` provides everything needed.

## Known Limitations

- **Public Packlink token** (e.g. `XG1TAqD3IYlUSCEQqEKaL` used in `https://pro.packlink.it/app/public/tracking/...`): this token is **only available from the Packlink Pro web dashboard** and is not returned by the API. Do not look for it — use the carrier URL from `packlink_track` instead.
- **ShipEngine fallback**: Labels are stored at `api.eu.shipengine.com/v1/downloads/10/` post-payment; usable when Packlink label generation fails.
