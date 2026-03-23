# Polymarket API Reference

## Gamma API (market metadata)
- Base: https://gamma-api.polymarket.com
- GET /markets — list active markets (paginate with offset/limit, max 100)
- GET /markets/{id} — single market detail
- Fields: question, outcomes, end_date, volume, active, closed, bestBid, bestAsk, spread
- Binary markets only (outcomes.length == 2)
- No auth required

## CLOB API (orderbook + trading)
- Base: https://clob.polymarket.com
- GET /book?token_id={id} — orderbook (bids/asks arrays with price+size)
- Orders via py-clob-client SDK (not raw HTTP)
- Order types: GTC (Good Till Cancelled) only — NEVER market orders
- Token IDs: each market has YES token_id and NO token_id
- Prices: 0.00 to 1.00 (represents probability in cents)
- Fees: 2% on profits (not on principal)

## py-clob-client SDK
- ClobClient(api_key, api_secret, api_passphrase, chain_id=POLYGON)
- create_and_post_order(OrderArgs) → order response
- OrderArgs(token_id, price, size, side, order_type)
- get_order(order_id) → order status
- cancel(order_id) → bool
- get_orders() → open orders list

## Key constraints
- Rate limit: ~10 req/sec on Gamma, stricter on CLOB
- Polygon chain — gas in MATIC, trading in USDC
- Spread = best_ask - best_bid (or |1 - YES - NO| as fallback)
- Market resolution: UMA oracle, can take hours after event
