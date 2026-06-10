# Kalshi market-data WebSocket feasibility (READ-ONLY)

_READ-ONLY MARKET DATA ONLY - NO ORDERS. Generated 2026-06-09 03:57:54 UTC. No orders, no paper/live, no promotion. Secrets are never printed (presence/booleans only)._

- series: KXBTC15M  ws_url: wss://external-api-ws.kalshi.com/trade-api/ws/v2
- dependencies: {'websockets': True, 'cryptography': True}
- credentials (presence only): {'key_id_present': True, 'private_key_path_present': True, 'private_key_readable': True, 'auth_configured': True, 'rsa_signing_lib_available': True, 'use_websocket_flag': True}
- active_ticker: KXBTC15M-26JUN090000-00
- **status: BLOCKED_CONNECT**
- blocker: other: TypeError

## Required (read-only market-data only) — env var NAMES (values never printed)
- KALSHI_KEY_ID
- KALSHI_PRIVATE_KEY_PATH
- KALSHI_PRIVATE_KEY_PASSPHRASE (optional)
- KALSHI_USE_WEBSOCKET=true

## Safety
- READ-ONLY MARKET DATA ONLY - NO ORDERS.
- Subscribed channels are market-data only (orderbook_delta); no order/portfolio endpoints.
- No live adapter used; live disabled; live_submission_allowed=false; no secrets printed.
