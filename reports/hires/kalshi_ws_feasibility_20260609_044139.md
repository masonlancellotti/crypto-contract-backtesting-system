# Kalshi market-data WebSocket feasibility (READ-ONLY)

_READ-ONLY MARKET DATA ONLY - NO ORDERS. Generated 2026-06-09 04:41:39 UTC. No orders, no paper/live, no promotion. Secrets are never printed (presence/booleans only)._

- series: KXBTC15M  ws_url: wss://external-api-ws.kalshi.com/trade-api/ws/v2
- dependencies: {'websockets': True, 'cryptography': True}
- websockets: version=16.0 header_arg=additional_headers
- websockets.sync.client.connect signature: `(uri: 'str', *, sock: 'socket.socket | None' = None, ssl: 'ssl_module.SSLContext | None' = None, server_hostname: 'str | None' = None, origin: 'Origin | None' = None, extensions: 'Sequence[ClientExtensionFactory] | None' = None, subprotocols: 'Sequence[Subprotocol] | None' = None, compression: 'str | None' = 'deflate', additional_headers: 'HeadersLike | None' = None, user_agent_header: 'str | None' = 'Python/3.13 websockets/16.0', proxy: 'str | Literal[True] | None' = True, proxy_ssl: 'ssl_module.SSLContext | None' = None, proxy_server_hostname: 'str | None' = None, open_timeout: 'float | None' = 10, ping_interval: 'float | None' = 20, ping_timeout: 'float | None' = 20, close_timeout: 'float | None' = 10, max_size: 'int | None | tuple[int | None, int | None]' = 1048576, max_queue: 'int | None | tuple[int | None, int | None]' = 16, logger: 'LoggerLike | None' = None, create_connection: 'type[ClientConnection] | None' = None, **kwargs: 'Any') -> 'ClientConnection'`
- credentials (presence only): {'key_id_present': True, 'private_key_path_present': True, 'private_key_readable': True, 'auth_configured': True, 'rsa_signing_lib_available': True, 'use_websocket_flag': True}
- active_ticker: KXBTC15M-26JUN090045-45
- **status: OK**
- blocker: none
- connected: True  subscribed: True
- connect_header_arg_used: additional_headers
- book messages: 458  updates/s: 15.27
- median interarrival ms: 9  **sub-second book updates available: True**
- message types: {'subscribed': 1, 'orderbook_snapshot': 1, 'orderbook_delta': 457}
- recv age ms: {'median': 55, 'p95': 59, 'max': 97}

## Safety
- READ-ONLY MARKET DATA ONLY - NO ORDERS.
- Subscribed channels are market-data only (orderbook_delta); no order/portfolio endpoints.
- No live adapter used; live disabled; live_submission_allowed=false; no secrets printed.
