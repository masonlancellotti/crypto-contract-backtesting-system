# Kalshi market-data WebSocket feasibility (READ-ONLY)

_READ-ONLY MARKET DATA ONLY - NO ORDERS. Generated 2026-06-09 03:37:20 UTC. No orders, no paper/live, no promotion. Secrets are never printed (presence/booleans only)._

- series: KXBTC15M  ws_url: wss://external-api-ws.kalshi.com/trade-api/ws/v2
- dependencies: {'websockets': True, 'cryptography': True}
- credentials (presence only): {'key_id_present': False, 'private_key_path_present': False, 'private_key_readable': False, 'auth_configured': False, 'rsa_signing_lib_available': True, 'use_websocket_flag': False}
- active_ticker: KXBTC15M-26JUN082345-45
- **status: BLOCKED_MISSING_CREDENTIALS**
- blocker: Kalshi market-data WS is auth-gated; set the read-only env vars below (values never printed) and KALSHI_USE_WEBSOCKET=true, then rerun.

## Required (read-only market-data only) — env var NAMES (values never printed)
- KALSHI_KEY_ID
- KALSHI_PRIVATE_KEY_PATH
- KALSHI_PRIVATE_KEY_PASSPHRASE (optional)
- KALSHI_USE_WEBSOCKET=true

## Safety
- READ-ONLY MARKET DATA ONLY - NO ORDERS.
- Subscribed channels are market-data only (orderbook_delta); no order/portfolio endpoints.
- No live adapter used; live disabled; live_submission_allowed=false; no secrets printed.
