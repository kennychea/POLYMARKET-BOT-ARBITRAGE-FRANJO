# Plan Edouard — Mis a jour 2026-04-01

> **`git pull origin Maitre-Chat`** pour avoir ce fichier a jour.
> Kenny coche tes taches quand tu confirmes qu'elles sont terminees.

---

## Regles de territoire (STRICTES)

| Zone | Edouard | Kenny |
|------|---------|-------|
| `core/` (scorer, fetcher, news, calibration) | **PROPRIETAIRE** | INTERDIT |
| `tests/test_scorer.py`, `test_fetcher.py`, `test_news.py`, `test_calibration.py` | **PROPRIETAIRE** | INTERDIT |
| `execution/` (sizing, clob, orders, portfolio) | **INTERDIT** | Proprietaire |
| `pipeline/` (orchestrator, scheduler) | **INTERDIT** | Proprietaire |
| `dashboard/` (api.py, app.jsx) | **INTERDIT** | Proprietaire |
| `infra/` (config.py, db.py, telegram.py) | **INTERDIT** | Proprietaire |
| `tests/` (tous les autres tests) | **INTERDIT** | Proprietaire |
| `infra/types.py` | **PARTAGE** — PR + accord des deux | **PARTAGE** |

### Imports autorises pour Edouard

```python
# OK — tu peux importer
from infra.types import TradingSignal, ScoringResult, EdgeResult, CalibrationBucket
import infra.config as cfg
import infra.db as db

# INTERDIT — ne jamais importer
from execution import ...    # NON
from pipeline import ...     # NON
from dashboard import ...    # NON
```

### Si tu as besoin d'une nouvelle constante dans `infra/config.py`

**Ne modifie PAS le fichier.** Dis a Kenny ce dont tu as besoin, il l'ajoute.
Exemple : "J'ai besoin de `CACHE_TTL_MARKETS: int = 300` dans config.py" → Kenny l'ajoute et push.

---

## Ce que Kenny fait en parallele (NE PAS TOUCHER)

Pour que tu saches ce qui se passe de son cote et eviter les conflits :

| Module | Ce que Kenny construit | Fichiers |
|--------|----------------------|----------|
| **execution/** | Sizing Kelly, CLOB orders, fill tracking, portfolio | `sizing.py`, `clob.py`, `orders.py`, `portfolio.py` |
| **pipeline/** | Orchestrator (paper + live), scheduler APScheduler | `orchestrator.py`, `scheduler.py` |
| **dashboard/** | FastAPI backend + React frontend | `api.py`, `app.jsx` |
| **infra/** | DB SQLite, Telegram alerts, config centralisee | `db.py`, `telegram.py`, `config.py` |
| **tests/** | Tests execution, pipeline, dashboard, db, telegram, scheduler, api | `test_db.py`, `test_telegram.py`, `test_scheduler.py`, `test_api.py` |

**Important :** Kenny gere le cablage entre `core/` et `execution/` dans `pipeline/orchestrator.py`.
Ton code dans `core/` expose des fonctions — Kenny les appelle depuis l'orchestrator.
Tu n'as **jamais** besoin de toucher a l'orchestrator.

---

## Sprint 1 — TERMINE

- [x] **Tache 1 : `core/calibration.py`** — scaffold avec 3 fonctions
  - `apply_calibration_adjustment()`, `is_calibrated()`, `get_calibration_report()`
  - 90 lignes, 194 lignes de tests (test_calibration.py)
- [x] **Tache 2 : Ameliorations `core/scorer.py`**
  - Prompts par categorie (politics, science, sports, geopolitics)
  - Mode second opinion avec detection divergence > 0.15
  - Validation pydantic (ScorerResponse model)
  - Tracking latence + tokens par appel
  - 250 lignes de tests
- [x] **Tache 3 : Ameliorations `core/fetcher.py`**
  - `fetch_price_history()` — momentum 24h
  - `fetch_orderbook_depth()` — liquidite bid/ask dans +/-2% du mid
  - Cache TTL en memoire (`_cache_get`, `_cache_set`, `clear_cache`)
  - 229 lignes de tests

### Note sur le Sprint 1

Tu as aussi modifie `pipeline/orchestrator.py` et `infra/config.py` dans ton commit `6ab616f`.
**Ces fichiers sont dans le territoire de Kenny.** Pour le futur :
- Si tu as besoin que l'orchestrator appelle une nouvelle fonction de `core/` → dis-le a Kenny
- Si tu as besoin d'une constante dans `config.py` → dis-le a Kenny
Kenny integre de son cote. Ca evite les conflits de merge.

---

## Sprint 2 — A FAIRE

### Tache 4 : Integrer calibration dans le scoring pipeline

- [ ] Dans `core/scorer.py` > `score_and_evaluate()` : apres le score, appeler `apply_calibration_adjustment()` sur la probabilite
  - Seulement si `is_calibrated()` retourne `True`
  - Logger l'ajustement : `logger.info("calibration_applied", extra={"raw": ..., "adjusted": ...})`
  - Si pas calibre : utiliser la probabilite brute, logger `"calibration_skipped_not_ready"`
- [ ] Mettre a jour les tests dans `tests/test_scorer.py`
- [ ] `pytest tests/test_scorer.py tests/test_calibration.py -v` — tout vert

### Tache 5 : Champ `category` dans MarketData

- [ ] Ajouter un champ `category: str = "default"` dans `core/fetcher.py` > `MarketData`
  - Les prompts par categorie dans scorer.py utilisent `getattr(market, "category", "default")` — ce champ le rend explicite
- [ ] Implementer `_detect_category(question: str) -> str` dans `core/fetcher.py`
  - Detection simple par mots-cles : "election|president|vote" → "politics", "FDA|trial|study" → "science", etc.
  - Fallback : `"default"`
- [ ] Appeler `_detect_category()` dans `parse_market()` pour remplir le champ
- [ ] Mettre a jour `tests/test_fetcher.py`
- [ ] `pytest tests/test_fetcher.py -v` — tout vert

### Tache 6 : Second opinion — moyenner les probabilites

- [ ] Dans `score_and_evaluate()` : quand `cfg.ENABLE_SECOND_OPINION` est True ET que `get_second_opinion()` retourne un resultat :
  - Si divergence <= 0.15 : `final_prob = (first.probability + second.probability) / 2`
  - Si divergence > 0.15 : garder `first.probability` mais set `data_quality = "low"`
  - Reconstruire le `ScoringResult` avec la probabilite finale
- [ ] Logger la decision : `logger.info("second_opinion_merged", extra={...})` ou `"second_opinion_diverged"`
- [ ] Mettre a jour `tests/test_scorer.py`
- [ ] `pytest tests/test_scorer.py -v` — tout vert

---

## Contraintes techniques (rappel)

- **Zero magic number** — tout depuis `infra.config`
- **Structured logging** — `logger.info("event", extra={...})`, jamais `print()`
- **Mock toutes les APIs** dans les tests — Anthropic, Gamma, Perplexity, tout
- **NE PAS modifier** `infra/types.py` sans PR + accord de Kenny
- **NE PAS toucher** a `execution/`, `pipeline/`, `dashboard/`, `infra/`
- **Type hints** partout, compatible `mypy --strict`
- **Si tu as besoin d'un changement dans un fichier de Kenny** → demande-lui, il push

---

## Commandes de verification

```bash
# Tests
pytest tests/test_calibration.py -v
pytest tests/test_scorer.py -v
pytest tests/test_fetcher.py -v
pytest tests/test_news.py -v

# Quality
mypy core/ --strict
ruff check core/

# Tout d'un coup
pytest tests/test_calibration.py tests/test_scorer.py tests/test_fetcher.py tests/test_news.py -v && mypy core/ --strict && ruff check core/
```
