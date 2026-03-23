# Polymarket Agent — AI Trading Bot

Bot de trading automatisé sur Polymarket via agents IA (Claude API).
Edge informationnel > edge vitesse. On joue les niches, pas les marchés saturés.

## Stack

Python 3.11 · py-clob-client · Claude API (Sonnet) · Perplexity API · SQLite · Telegram · Polygon (USDC)

## Architecture

```
core/           → Data + scoring (Owner: Edouard)
  fetcher.py        Polymarket Gamma API, filtres marchés
  news.py           RSS + Perplexity + GDELT, sentiment
  scorer.py         Claude API scoring, JSON probability output
  calibration.py    Backtesting, calibration buckets

execution/      → CLOB + risk (Owner: Partner)
  clob.py           py-clob-client wrapper, order routing
  sizing.py         Kelly fractionné, position management
  portfolio.py      Positions ouvertes, exposure tracking
  orders.py         Fill tracking, cancellations

infra/          → Shared (PR review des deux)
  db.py             SQLite schema + helpers
  config.py         CONFIG dict centralisé
  telegram.py       Alertes temps réel

pipeline/       → Orchestration (Owner: Edouard, après core stable)
  orchestrator.py   Main loop (--paper / --live)
  scheduler.py      APScheduler, cycle 15min

dashboard/      → Monitoring (Owner: Partner, après execution stable)
  app.py            Streamlit P&L + calibration viz
```

## Contrat d'interface (NE PAS MODIFIER sans PR + accord des deux)

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

## Thresholds (NE PAS CHANGER sans discussion)

```python
MIN_EDGE_NET = 0.05
MIN_CONFIDENCE = 6
KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.08          # 8% bankroll max par trade
MAX_SIMULTANEOUS_POSITIONS = 5
CYCLE_INTERVAL_SECONDS = 900     # 15 min
MIN_TRADE_SIZE = 3.0             # USDC (gas + frais)
POLYMARKET_FEE = 0.02            # 2% sur gains
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

## Commandes

```bash
# Paper trading (un cycle)
python -m pipeline.orchestrator --paper --once

# Paper trading (continu, 15min)
python -m pipeline.orchestrator --paper

# Live trading
python -m pipeline.orchestrator --live

# Scorer un marché manuellement
python -m core.scorer --market-id "xxx" --verbose

# Check calibration (après 20+ trades résolus)
python -m core.calibration --last-n 100

# Dashboard
streamlit run dashboard/app.py
```

## MCP Polymarket (IQ AI)

```bash
npm install @iqai/mcp-polymarket
```

Utilise le MCP pour interroger les marchés directement en session Claude Code (discovery, orderbook, history).

## Git Workflow

```
main  ← merge via PR uniquement, tests verts
├── dev  ← intégration
│   ├── feat/core-*     ← branches Edouard
│   ├── feat/exec-*     ← branches Partner
│   └── fix/*           ← hotfixes
```

Jamais de push direct sur `main` ou `dev`. PR obligatoire avec review.

## Règles de dev

- Secrets via `.env` uniquement — jamais en dur, jamais dans un prompt Claude
- Toutes les fonctions typées (mypy strict)
- Tests pour toute fonction critique
- Logs structurés : `logger.info("event", extra={"market_id": ..., "edge": ...})`
- Pas de magic numbers — tout dans `infra/config.py`
- Ne jamais modifier le schéma DB sans migration + PR

## Sécurité

- Les clés privées wallet ne passent JAMAIS dans un prompt LLM
- Limit orders uniquement (jamais de market orders)
- Slippage max 2% hardcodé
- Circuit breaker : -20% bankroll en 7 jours → pause + audit

## État du projet

- [ ] infra/db.py
- [ ] infra/config.py
- [ ] core/fetcher.py — Gamma API + filtres
- [ ] core/news.py — Perplexity + RSS
- [ ] core/scorer.py — Claude scoring engine
- [ ] execution/sizing.py — Kelly fractionné
- [ ] execution/clob.py — py-clob-client wrapper
- [ ] execution/portfolio.py — positions ouvertes
- [ ] pipeline/orchestrator.py — BLOCKED (attend core stable)
- [ ] core/calibration.py — BLOCKED (attend 100 signaux)
- [ ] dashboard/app.py — BLOCKED (attend execution stable)

## Phases

1. **Setup** — repo, .env, MCP, Obsidian vault
2. **Build** — core/ + execution/ en parallèle
3. **Paper** — 100 signaux, calibration error < 0.08 requis pour passer en live
4. **Live petit** — $50-100 USDC, semi-auto, 30 trades
5. **Full-auto** — edge > 7% + confidence >= 7
6. **Scale** — capital progressif si 2 mois consécutifs profitables
