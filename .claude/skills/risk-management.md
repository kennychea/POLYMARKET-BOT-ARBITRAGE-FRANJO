# Risk Management & Position Sizing

## Kelly Criterion (fractional)
- Full Kelly: (b*p - q) / b where b = market odds, p = prob_win, q = 1-p
- ALWAYS use fraction = 0.25 (quarter Kelly) — never full Kelly
- Cap: max 8% of bankroll per position
- Min trade: $5 USDC (below this, gas eats the profit)

## Portfolio constraints
- Max 5 simultaneous open positions
- No more than 2 positions in same category
- Total exposure never exceeds 40% of bankroll

## Circuit breaker
- If P&L in last 7 days < -20% of bankroll → STOP all trading
- Manual review required to restart
- Log the trigger, send Telegram alert

## Order execution
- LIMIT orders only — never market orders
- Limit price = best_ask + 0.005 (slightly aggressive for fill)
- Max slippage: 2% above current price → skip if exceeded
- GTC order type — cancel manually if market moves against

## Anti-patterns
- Never chase a fill by increasing limit price repeatedly
- Never average down on a losing position
- Never override circuit breaker programmatically
- Never risk more than Kelly suggests, even on "sure things"