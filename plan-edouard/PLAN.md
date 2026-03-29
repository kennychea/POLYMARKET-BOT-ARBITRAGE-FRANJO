# Plan Edouard — Sprint 1

> **Pull depuis `Maitre-Chat`** pour avoir ce fichier a jour.
> Kenny coche les taches quand tu confirmes qu'elles sont terminees.

---

## Regles de territoire

| Zone | Edouard | Kenny |
|------|---------|-------|
| `core/` (scorer, fetcher, news, calibration) | **Proprietaire** | INTERDIT |
| `tests/test_scorer.py`, `test_fetcher.py`, `test_news.py` | **Proprietaire** | INTERDIT |
| `execution/`, `pipeline/`, `dashboard/` | INTERDIT | Proprietaire |
| `infra/` (config, db, telegram) | INTERDIT | Proprietaire |
| `infra/types.py` | **PARTAGE** — PR + accord des deux | **PARTAGE** |

**Import uniquement depuis `infra.types` et `infra.db`** — jamais depuis `execution/` ou `pipeline/`.

---

## Tache 1 : `core/calibration.py` (scaffold)

- [ ] Creer `core/calibration.py`
- [ ] Implementer `apply_calibration_adjustment(raw_prob: float, buckets: list[CalibrationBucket]) -> float`
  - Ajuste la probabilite brute du scorer selon les buckets de calibration existants
  - Si aucun bucket n'a assez de data (`count < 5`), retourner `raw_prob` tel quel
- [ ] Implementer `is_calibrated(buckets: list[CalibrationBucket], max_error: float = 0.08) -> bool`
  - Retourne `True` si l'erreur moyenne de tous les buckets est < `max_error`
  - Ignorer les buckets vides (`count == 0`)
- [ ] Implementer `get_calibration_report() -> dict`
  - Utilise `db.compute_calibration()` qui existe deja dans `infra/db.py`
  - Retourne : `{"buckets": [...], "is_calibrated": bool, "mean_error": float, "total_signals": int}`
- [ ] Imports autorises : `infra.types` (CalibrationBucket), `infra.db` (compute_calibration), `infra.config`
- [ ] Creer `tests/test_calibration.py` avec couverture complete (min 10 tests)
- [ ] Tous les tests passent : `pytest tests/test_calibration.py -v`

### Signatures de reference

```python
# infra/types.py — CalibrationBucket (deja existant, NE PAS MODIFIER)
@dataclass
class CalibrationBucket:
    bucket_low: float
    bucket_high: float
    predicted_prob: float   # mean agent_probability in this bucket
    actual_win_rate: float  # actual wins / total in bucket
    count: int
    error: float            # |predicted_prob - actual_win_rate|

# infra/db.py — deja existant
def compute_calibration(last_n: int = 100) -> list[CalibrationBucket]: ...
```

---

## Tache 2 : Ameliorations `core/scorer.py`

- [ ] **Prompts par categorie** — adapter le prompt Claude selon le type de marche :
  - Politique, Science, Sport, Crypto, Autre
  - Detecter la categorie depuis `question` ou ajouter un champ si necessaire
- [ ] **Mode "second opinion"** — faire 2 appels Claude avec des prompts differents
  - Si divergence > 0.15 entre les deux : flag `data_quality = "low"` + logger un warning
  - Sinon : moyenne des deux probabilites
- [ ] **Validation pydantic** des reponses JSON Claude
  - Le scorer parse la reponse Claude — valider avec pydantic que le JSON est conforme
  - Si validation echoue : retry 1 fois, puis `data_quality = "low"`
- [ ] **Tracking latence + tokens** par appel
  - Logger `duration_ms` et `tokens_used` (input + output) pour chaque appel Claude
  - Format : `logger.info("scorer_call", extra={"duration_ms": ..., "tokens_input": ..., "tokens_output": ...})`
- [ ] Mettre a jour `tests/test_scorer.py` pour couvrir les nouveaux cas
- [ ] Tous les tests passent : `pytest tests/test_scorer.py -v`

---

## Tache 3 : Ameliorations `core/fetcher.py`

- [ ] **Prix historique 24h (momentum)**
  - Ajouter une fonction ou enrichir les donnees marche avec le prix il y a 24h
  - Calculer `momentum_24h = current_price - price_24h_ago`
  - Si l'API Gamma ne fournit pas l'historique, documenter la limitation
- [ ] **Profondeur du carnet d'ordres (liquidite)**
  - Recup la profondeur bid/ask du CLOB pour chaque marche
  - Ajouter `liquidity_score` ou equivalent aux donnees retournees
  - Marches avec spread > 10% = flag low liquidity
- [ ] **Cache avec TTL**
  - Eviter les appels redondants a l'API Gamma
  - TTL = `cfg.CYCLE_INTERVAL_SECONDS` (15 min par defaut)
  - Utiliser un dict en memoire avec timestamp, pas de dep externe
- [ ] Mettre a jour `tests/test_fetcher.py` pour couvrir les nouveaux cas
- [ ] Tous les tests passent : `pytest tests/test_fetcher.py -v`

---

## Contraintes techniques

- **Zero magic number** — tout depuis `infra.config`
- **Structured logging** — `logger.info("event", extra={...})`, jamais `print()`
- **Mock toutes les APIs** dans les tests — Anthropic, Gamma, tout
- **Ne pas modifier** `infra/types.py` sans PR + accord de Kenny
- **Ne pas toucher** a `execution/`, `pipeline/`, `dashboard/`, `infra/`
- **Type hints** partout, compatible `mypy --strict`

---

## Commandes de verification

```bash
pytest tests/test_calibration.py -v    # Tache 1
pytest tests/test_scorer.py -v         # Tache 2
pytest tests/test_fetcher.py -v        # Tache 3
mypy core/ --strict                    # Type check
ruff check core/                       # Lint
```
