# Probability Scoring & Calibration

## Scoring philosophy
- The agent's edge is INFORMATIONAL, not speed-based
- Claude estimates P(event) independently, then compares to market price
- Edge = P(agent) - P(market) - fees(0.02)
- A trade is valid only when: edge > 0.05 AND confidence >= 6

## Calibration rules
- When Claude says 70%, it must happen ~70% of the time
- Overconfidence is the #1 failure mode — penalize it
- If data is insufficient → confidence < 5 → do NOT trade
- NEVER anchor to the current market price when estimating probability
- Always consider: base rates, recency bias, availability bias

## Edge computation
- edge_yes = agent_prob - market_yes_price
- edge_no = (1 - agent_prob) - market_no_price
- Subtract POLYMARKET_FEE (0.02) from both
- Pick the side with higher net edge
- Tradeable = edge_net > MIN_EDGE_NET (0.05) AND confidence >= MIN_CONFIDENCE (6)

## Calibration measurement
- After 20+ resolved trades, check by probability bucket (0.1 increments)
- calibration_error = avg(|predicted_prob - actual_winrate|) per bucket
- Target: calibration_error < 0.08 before going live
- Brier score as secondary metric

## Anti-patterns to avoid
- Scoring crypto price markets (too efficient, bots everywhere)
- Markets with < $1k volume (illiquid, manipulation risk)
- Markets resolving in < 2 days (gas costs eat the edge)
- Trusting a single news source without cross-referencing
