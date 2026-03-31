# Copilot Agent Instructions — Polymarket Bot

## CRITICAL: Parallel Work with Claude Code

Tu travailles EN PARALLELE avec Claude Code. Pour eviter les conflits:

### ZONES RESERVEES A COPILOT (tu peux toucher librement)
- `dashboard/` — UI React, composants, styles
- `docs/` — documentation (sauf architecture.md)
- `tests/test_dashboard*.py` — tests dashboard
- `static/`, `assets/` — fichiers statiques si besoin

### ZONES INTERDITES (Claude Code les gere)
- `core/` — scorer, fetcher, news, calibration
- `execution/` — sizing, clob, orders, portfolio
- `pipeline/` — orchestrator, scheduler
- `infra/` — config, db, types, telegram
- `tests/` (sauf test_dashboard*)
- `CLAUDE.md`
- `tasks/`
- `.claude/`

### ZONES PARTAGEES (coordination requise)
- `pyproject.toml` — si tu dois ajouter une dep, ajoute-la UNIQUEMENT dans une section `[project.optional-dependencies.dashboard]`
- `Makefile` — ajoute tes targets avec prefix `dash-` (ex: `dash-dev`, `dash-build`)
- `README.md` — ne modifie que la section "Dashboard" si elle existe

## REGLES DU PROJET

### Architecture
```
core/     → logique metier (scoring, fetcher, news)
execution/ → execution trades (orders, portfolio, sizing)
pipeline/  → orchestration (scheduler, orchestrator)
infra/     → config, DB, types, telegram
dashboard/ → UI + API backend
```

### Imports
- NE PAS cross-importer entre core/ et execution/
- Direction autorisee: core/ → infra/ ← execution/
- dashboard/ peut importer depuis infra/ uniquement

### Code style
- Python: ruff + mypy strict
- Pas de print() — utiliser logging
- Pas de magic numbers — tout dans infra/config.py
- Pas de secrets dans le code — tout en .env

### Types partages (NE PAS MODIFIER)
Les dataclasses dans `infra/types.py` sont gelees:
- TradingSignal, Position, ScoringResult, EdgeResult, OrderResult, CalibrationBucket
- Si tu as besoin d'un nouveau type pour le dashboard, cree-le dans `dashboard/types.py`

### Tests
- Toujours mocker les APIs externes
- Ne pas toucher aux fixtures des autres modules
- Tes tests dashboard dans `tests/test_dashboard*.py`

### Git
- Branche actuelle: `Edouard`
- Prefix tes commits: `dash:` ou `ui:` pour qu'on distingue ton travail
- Ne pas force-push

## THRESHOLDS (reference, ne pas modifier)
```python
MIN_EDGE_NET = 0.05
MIN_CONFIDENCE = 6
KELLY_FRACTION = 0.25
MAX_POSITION_PCT = 0.08
MAX_SIMULTANEOUS_POSITIONS = 5
MIN_TRADE_SIZE = 5.0
POLYMARKET_FEE = 0.02
```

## COMMANDES
```bash
pytest tests/test_dashboard* -v    # Tests dashboard
ruff check dashboard/              # Lint dashboard
mypy dashboard/ --strict           # Types dashboard
```
