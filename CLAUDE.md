# Polymarket Agent — AI Trading Bot

Bot de trading automatisé sur Polymarket via agents IA (Claude API).
Edge informationnel > edge vitesse. On joue les niches, pas les marchés saturés.

## DÉMARRAGE DE SESSION

1. Lire `tasks/lessons.md` — appliquer toutes les leçons avant de toucher quoi que ce soit
2. Lire `tasks/todo.md` — comprendre l'état actuel
3. Si aucun des deux n'existe, les créer avant de commencer
4. Lire les skills pertinents dans `.claude/skills/` selon la tâche

## WORKFLOW

### 1. Planifier d'abord
- Passer en mode plan pour toute tâche non triviale (3+ étapes)
- Écrire le plan dans `tasks/todo.md` avant d'implémenter
- Si quelque chose ne va pas, STOP et re-planifier — ne jamais forcer

### 2. Stratégie sous-agents
- Utiliser des sous-agents pour garder le contexte principal propre
- Une tâche par sous-agent
- Investir plus de compute sur les problèmes difficiles
- Agents disponibles : scorer, executor, data-pipeline, reviewer, tester, infra

### 3. Boucle d'auto-amélioration
- Après toute correction : mettre à jour `tasks/lessons.md`
- Format : `[date] | ce qui a mal tourné | règle pour l'éviter`
- Relire les leçons à chaque démarrage de session

### 4. Standard de vérification
- Ne jamais marquer comme terminé sans preuve que ça fonctionne
- Lancer les tests, vérifier les logs, comparer le comportement
- Se demander : « Est-ce qu'un staff engineer validerait ça ? »

### 5. Exiger l'élégance
- Pour les changements non triviaux : existe-t-il une solution plus élégante ?
- Si un fix semble bricolé : le reconstruire proprement
- Ne pas sur-ingénieriser les choses simples

### 6. Correction de bugs autonome
- Quand on reçoit un bug : le corriger directement
- Aller dans les logs, trouver la cause racine, résoudre
- Pas besoin d'être guidé étape par étape

## PRINCIPES FONDAMENTAUX

- Simplicité d'abord — toucher un minimum de code
- Pas de paresse — causes racines uniquement, pas de fixes temporaires
- Ne jamais supposer — vérifier chemins, APIs, variables avant utilisation
- Demander une seule fois — une question en amont si nécessaire, ne jamais interrompre en cours de tâche

## GESTION DES TÂCHES

1. **Planifier** → `tasks/todo.md`
2. **Vérifier** → confirmer avant d'implémenter
3. **Suivre** → marquer comme terminé au fur et à mesure
4. **Expliquer** → résumé de haut niveau à chaque étape
5. **Apprendre** → `tasks/lessons.md` après corrections

## APPRENTISSAGES

(Claude remplit cette section au fil du temps dans `tasks/lessons.md`)

---

## Stack

Python 3.11 · py-clob-client · Claude API (Sonnet) · Perplexity API · SQLite · Telegram · Polygon (USDC)

## Architecture

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
MIN_TRADE_SIZE = 5.0             # USDC minimum
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

# Tests
pytest tests/ -v

# Type check
mypy core/ execution/ infra/ pipeline/ --strict

# Dashboard
streamlit run dashboard/app.py
```

## MCP Polymarket (IQ AI)

```bash
npm install @iqai/mcp-polymarket
```

Utilise le MCP pour interroger les marchés directement en session Claude Code.

## Git Workflow

```
main  ← merge via PR uniquement, tests verts
├── dev  ← intégration
│   ├── feat/core-*     ← branches Edouard
│   ├── feat/exec-*     ← branches Franjo
│   └── fix/*           ← hotfixes
```

Jamais de push direct sur `main` ou `dev`. PR obligatoire avec review.
Commit format : `feat(core):`, `feat(exec):`, `feat(infra):`, `fix():`, `test():`, `docs:`

## Règles de dev

- Secrets via `.env` uniquement — jamais en dur, jamais dans un prompt Claude
- Toutes les fonctions typées (mypy strict)
- Tests pour toute fonction critique — mock all external APIs
- Logs structurés : `logger.info("event", extra={"market_id": ..., "edge": ...})`
- Pas de magic numbers — tout dans `infra/config.py`
- Ne jamais modifier le schéma DB sans migration + PR
- Dependency direction : `core/ → infra/ ← execution/`, jamais de cross-import

## Sécurité

- Les clés privées wallet ne passent JAMAIS dans un prompt LLM
- Limit orders uniquement (jamais de market orders)
- Slippage max 2% hardcodé
- Circuit breaker : -20% bankroll en 7 jours → pause + audit

## Ce qu'il ne faut PAS faire

- NE PAS utiliser de market orders — limit only
- NE PAS hardcoder de threshold — tout depuis infra.config
- NE PAS commit .env ou un secret
- NE PAS ajouter de deps sans mettre à jour pyproject.toml
- NE PAS modifier TradingSignal/Position sans update all consumers
- NE PAS appeler de vraies APIs dans les tests — toujours mock
- NE PAS trader si confidence < 6 ou edge_net < 0.05
- NE PAS dépasser 5 positions simultanées

## État du projet

- [x] infra/db.py
- [x] infra/config.py
- [x] infra/types.py — TradingSignal, Position, CalibrationBucket, ScoringResult, EdgeResult, OrderResult
- [x] infra/telegram.py — send_alert, format_trade_alert, format_scan_alert
- [x] core/fetcher.py — Gamma API + filters, 35 tests green
- [ ] core/news.py — Perplexity + RSS
- [ ] core/scorer.py — Claude scoring engine
- [ ] execution/sizing.py — Kelly fractionné
- [ ] execution/clob.py — py-clob-client wrapper
- [ ] execution/portfolio.py — positions ouvertes
- [ ] execution/orders.py — fill tracking
- [ ] pipeline/orchestrator.py — BLOCKED (attend core + execution stable)
- [ ] pipeline/scheduler.py — BLOCKED
- [ ] core/calibration.py — BLOCKED (attend 100 signaux)
- [ ] dashboard/app.py — BLOCKED (attend execution stable)

## Phases

1. **Setup** ✅ — repo, .env, MCP, skills, agents
2. **Build** ← ON EST ICI — core/ + execution/ en parallèle
3. **Paper** — 100 signaux, calibration error < 0.08 requis pour passer en live
4. **Live petit** — $50-100 USDC, semi-auto, 30 trades
5. **Full-auto** — edge > 7% + confidence >= 7
6. **Scale** — capital progressif si 2 mois consécutifs profitables