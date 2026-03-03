---
name: luffa-card-purchase
description: >
  Use this skill when the user wants to buy, apply for, or get a Luffa Card.
  Triggers on: "luffa card", "apply card", "buy card", "get card", "card offer",
  "apply for card", "i want a card", "card application", "purchase card".
  Guides the full end-to-end flow using MCP tools — wallet check, KYC, balance
  check, user confirmation (YES/NO gate), profile collection, and card submission.
---

# Luffa Card Purchase Skill

Handles the complete Luffa Card application flow using MCP tools.

## Flow Summary
1. `get_wallet_info` — check balance + card status
2. `get_card_offers` — show available cards
3. `check_kyc_status` — verify identity
4. `check_sufficient_balance` — compare balance vs fee
5. **⚠️ STOP — ask user YES/NO confirmation**
6. Handle reply — proceed or cancel
7. `get_user_profile` — collect missing fields
8. `submit_card_application(confirmed=true)` — apply + deduct fee

## Critical Rules
- Never call `submit_card_application` with `confirmed=true` without explicit YES from user
- Always show the exact fee amount before asking for confirmation
- If NO → cancel immediately, no tools called
- Top-up flow: call `top_up_wallet` then resume from Step 4