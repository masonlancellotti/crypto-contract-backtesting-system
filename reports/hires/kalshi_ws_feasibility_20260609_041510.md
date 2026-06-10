# Kalshi market-data WebSocket feasibility (READ-ONLY)

_READ-ONLY MARKET DATA ONLY - NO ORDERS. Generated 2026-06-09 04:15:10 UTC. No orders, no paper/live, no promotion. Secrets are never printed (presence/booleans only)._

- series: KXBTC15M  ws_url: wss://external-api-ws.kalshi.com/trade-api/ws/v2
- dependencies: {'websockets': True, 'cryptography': True}
- websockets: version=16.0 header_arg=additional_headers
- websockets.sync.client.connect signature: `(uri: 'str', *, sock: 'socket.socket | None' = None, ssl: 'ssl_module.SSLContext | None' = None, server_hostname: 'str | None' = None, origin: 'Origin | None' = None, extensions: 'Sequence[ClientExtensionFactory] | None' = None, subprotocols: 'Sequence[Subprotocol] | None' = None, compression: 'str | None' = 'deflate', additional_headers: 'HeadersLike | None' = None, user_agent_header: 'str | None' = 'Python/3.13 websockets/16.0', proxy: 'str | Literal[True] | None' = True, proxy_ssl: 'ssl_module.SSLContext | None' = None, proxy_server_hostname: 'str | None' = None, open_timeout: 'float | None' = 10, ping_interval: 'float | None' = 20, ping_timeout: 'float | None' = 20, close_timeout: 'float | None' = 10, max_size: 'int | None | tuple[int | None, int | None]' = 1048576, max_queue: 'int | None | tuple[int | None, int | None]' = 16, logger: 'LoggerLike | None' = None, create_connection: 'type[ClientConnection] | None' = None, **kwargs: 'Any') -> 'ClientConnection'`
- credentials (presence only): {'key_id_present': True, 'private_key_path_present': True, 'private_key_readable': True, 'auth_configured': True, 'rsa_signing_lib_available': True, 'use_websocket_flag': True}
- active_ticker: KXBTC15M-26JUN090030-30
- **status: BLOCKED_CONNECT**
- blocker: other: TypeError
- connect_header_arg_used: additional_headers

## Sanitized exception
- type: TypeError
- message: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'

## Sanitized traceback
```text
Traceback (most recent call last):
  File "C:\Users\mason\Downloads\polymarket-btc-five-mins\src\btc5m\venues\kalshi\hires\kalshi_ws.py", line 409, in _probe
    book.apply_delta(m.get("msg") or {})
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mason\Downloads\polymarket-btc-five-mins\src\btc5m\venues\kalshi\hires\kalshi_ws.py", line 198, in apply_delta
    price = int(msg.get("price"))
TypeError: int() argument must be a string, a bytes-like object or a real number, not 'NoneType'
```

## Required (read-only market-data only) — env var NAMES (values never printed)
- KALSHI_KEY_ID
- KALSHI_PRIVATE_KEY_PATH
- KALSHI_PRIVATE_KEY_PASSPHRASE (optional)
- KALSHI_USE_WEBSOCKET=true

## Safety
- READ-ONLY MARKET DATA ONLY - NO ORDERS.
- Subscribed channels are market-data only (orderbook_delta); no order/portfolio endpoints.
- No live adapter used; live disabled; live_submission_allowed=false; no secrets printed.
