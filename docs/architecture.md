# Architecture — Polymarket Agent

## Stack

Python 3.11 · py-clob-client · Claude API (Sonnet) · Perplexity API · SQLite · Telegram · Polygon (USDC)

## Structure des modules

```
core/           → Data + scoring (Owner: Edouard)
  fetcher.py        Polymarket Gamma API, filtres marchés
  news.py           RSS + Perplexity + GDELT, sentiment
  scorer.py         Claude API scoring, JSON probability output
  calibration.py    Backtesting, calibration buckets

execution/      → CLOB + risk (Owner: Franjo)
  clob.py           py-clob-client wrapper, order routing
  sizing.py         Kelly fractionné, position management
  portfolio.py      Positions ouvertes, exposure tracking
  orders.py         Fill tracking, cancellations

infra/          → Shared (PR review des deux)
  db.py             SQLite schema + helpers
  config.py         CONFIG dict centralisé
  types.py          Shared domain contracts (TradingSignal, Position, ScoringResult, EdgeResult, OrderResult)
  telegram.py       Alertes temps réel

pipeline/       → Orchestration (Owner: Edouard, après core stable)
  orchestrator.py   Main loop (--paper / --live)
  scheduler.py      APScheduler, cycle 15min

dashboard/      → Monitoring (Owner: Franjo, après execution stable)
  app.py            Streamlit P&L + calibration viz
```

## Contrat d'interface

```python
@dataclass
class TradingSignal:
    market_id: str
    question: str
    side: Literal["YES", "NO"]
    agent_probability: float      # 0.0-1.0
    market_probability: float     # prix actuel
    edge_net: float               # après frais 2%
    confidence: int               # 0-10
    tradeable: bool
    news_context: str
    timestamp: datetime

@dataclass
class Position:
    position_id: str
    signal: TradingSignal
    entry_price: float
    size_usdc: float
    size_shares: float
    order_id: str
    status: Literal["open", "won", "lost", "void", "cancelled"]
    pnl: Optional[float]
```

## Filtres marchés

```python
MARKET_FILTERS = {
    "volume_min": 1_000,
    "volume_max": 50_000,         # sous le radar des gros bots
    "days_to_resolution": (2, 30),
    "spread_max": 0.04,
    "price_range": (0.10, 0.90),
    "category_blacklist": ["crypto_price"],
    "category_focus": ["politics", "science", "sports_outcome", "geopolitics"],
}
```

## Data flow

```
[Gamma API] → fetcher.py → list[MarketData]
                               ↓
[Perplexity + RSS] → news.py → news_context: str
                               ↓
               scorer.py → ScoringResult → EdgeResult → TradingSignal
                               ↓
               sizing.py → position_size: float (Kelly + risk checks)
                               ↓
               clob.py → OrderResult (limit order on CLOB)
                               ↓
               db.py → log trade + telegram.py → alert
```

## Git Workflow

```
main  ← merge via PR uniquement, tests verts
├── dev  ← intégration
│   ├── feat/core-*     ← branches Edouard
│   ├── feat/exec-*     ← branches Franjo
│   └── fix/*           ← hotfixes
```

Commit format : `feat(core):`, `feat(exec):`, `feat(infra):`, `fix():`, `test():`, `docs:`

## Règles de dev

- Secrets via `.env` uniquement — jamais en dur
- Toutes les fonctions typées (mypy strict)
- Tests pour toute fonction critique — mock all external APIs
- Logs structurés : `logger.info("event", extra={"market_id": ..., "edge": ...})`
- Dependency direction : `core/ → infra/ ← execution/`, jamais de cross-import
- Ne jamais modifier le schéma DB sans migration + PR

## Sécurité

- Les clés privées wallet ne passent JAMAIS dans un prompt LLM
- Limit orders uniquement (jamais de market orders)
- Slippage max 2% hardcodé
- Circuit breaker : -20% bankroll en 7 jours → pause + audit

## MCP Polymarket (IQ AI)

```bash
npm install @iqai/mcp-polymarket
```

## Phases

1. **Setup** ✅ — repo, .env, MCP, skills, agents
2. **Build** ← ON EST ICI — core/ + execution/ en parallèle
3. **Paper** — 100 signaux, calibration error < 0.08 requis pour passer en live
4. **Live petit** — $50-100 USDC, semi-auto, 30 trades
5. **Full-auto** — edge > 7% + confidence >= 7
6. **Scale** — capital progressif si 2 mois consécutifs profitables
