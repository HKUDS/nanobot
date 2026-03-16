---
name: waiaas
description: Self-hosted crypto wallet daemon for AI agents. Send transactions, manage DeFi, enforce spending limits — without exposing private keys. EVM + Solana via MCP.
homepage: https://waiaas.ai
metadata: {"nanobot":{"emoji":"🔐","requires":{"bins":["waiaas"],"env":["WAIAAS_SESSION_TOKEN"]},"install":[{"kind":"node","package":"@waiaas/cli","bins":["waiaas"]}]}}
---

# WAIaaS — Self-Hosted Crypto Wallet

> Your private keys should never live inside your agent process. WAIaaS is a local daemon that holds keys in an isolated process and enforces spending policies.

## Setup

The daemon operator (human) sets up WAIaaS before agents can use it:

```bash
npm install -g @waiaas/cli
waiaas init
waiaas start
waiaas quickset --mode mainnet
```

`quickset` creates Solana + EVM wallets, issues session tokens, and prints MCP config.

Configure spending policies via Admin UI at `http://127.0.0.1:3100/admin` before connecting agents.

### Connect via MCP

Set the session token as environment variable:

```bash
export WAIAAS_SESSION_TOKEN="<session-token-from-quickset>"
```

Add to nanobot MCP config:

```yaml
mcpServers:
  waiaas:
    command: npx
    args: ["@waiaas/mcp"]
    env:
      WAIAAS_SESSION_TOKEN: "${WAIAAS_SESSION_TOKEN}"
```

Or auto-register: `waiaas mcp setup --all`

> **Security:** Store tokens in environment variables, not plaintext config. Tokens are time-limited JWTs, revocable from Admin UI.

## How to Use

**Always call `connect_info` first** to discover wallets, policies, and capabilities.

### Core operations

- `get_balance` / `get_assets` — Check balances (native + tokens)
- `send_token` — Send native (SOL/ETH) or tokens. Params: `to`, `amount`, `token`, `network`
- `simulate_transaction` — Preview fees and policy tier before executing
- `sign_message` — Personal sign or EIP-712 typed data
- `list_transactions` / `list_incoming_transactions` — Transaction history

### DeFi (action providers)

- **Swap**: Jupiter (Solana), 0x (EVM)
- **Bridge**: LI.FI, Across
- **Lending**: Aave V3 (EVM), Kamino (Solana)
- **Staking**: Lido (ETH), Jito (SOL)
- **Yield**: Pendle
- **Perp**: Drift (Solana), Hyperliquid
- **Prediction**: Polymarket

### NFT

- `list_nfts` — ERC-721, ERC-1155, Metaplex
- `get_nft_metadata` — Metadata and attributes
- `transfer_nft` — Requires APPROVAL tier

### Advanced

- `x402_fetch` — Auto-pay HTTP 402 responses
- `wc_connect` — WalletConnect pairing for owner approval
- `build_userop` / `sign_userop` — ERC-4337 Account Abstraction
- `get_rpc_proxy_url` — RPC proxy for Forge/Hardhat

## Security Model

- **Session tokens**: Time-limited JWTs. Never the master password.
- **Default-deny**: Token whitelist, contract whitelist, spending limits.
- **4 tiers**: AUTO_SIGN → TIME_DELAY → APPROVAL → BLOCKED.
- **Kill switch**: Instantly freeze any wallet from Admin UI.

## Links

- Website: https://waiaas.ai
- GitHub: https://github.com/minhoyoo-iotrust/WAIaaS
- npm: `@waiaas/cli` · `@waiaas/sdk` · `@waiaas/mcp`
