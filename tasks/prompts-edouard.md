# Prompts Edouard — Branche Edouard

Ordre d'execution : 1 → 2 → 4 → 3 → 5 → 6
(1, 4 et 5 peuvent aller en parallele si tu veux)

Copie-colle UN prompt par conversation Claude Code.
Apres chaque prompt, verifie que les tests passent avant de passer au suivant.

---

## PROMPT 1 — core/calibration.py (scaffold)

```
Cree le fichier core/calibration.py — module de calibration pour le scorer.

Context : on est sur la branche Edouard. infra/db.py a deja compute_calibration()
qui retourne list[CalibrationBucket]. infra/types.py a CalibrationBucket (frozen dataclass).
Le module NE DOIT importer QUE depuis infra.types et infra.db (pas de cross-import avec execution/).

Implemente exactement 3 fonctions :

1. apply_calibration_adjustment(raw_prob: float, buckets: list[CalibrationBucket]) -> float
   - Trouve le bucket correspondant a raw_prob (intervalle 0.1)
   - Si le bucket a assez de samples (>= 10), applique un ajustement lineaire :
     adjusted = raw_prob + (bucket.actual_win_rate - bucket.predicted_prob)
   - Clamp le resultat entre 0.01 et 0.99
   - Si pas assez de samples ou pas de bucket : retourner raw_prob tel quel

2. is_calibrated(buckets: list[CalibrationBucket], max_error: float = 0.08) -> bool
   - Retourne True si TOUS les buckets avec >= 10 samples ont error <= max_error
   - Si aucun bucket n'a >= 10 samples, retourner False (pas assez de donnees)

3. get_calibration_report() -> dict
   - Appelle db.compute_calibration() pour recuperer les buckets
   - Retourne un dict avec :
     - "buckets": liste de dicts (range, predicted, actual, error, samples)
     - "is_calibrated": bool (appel a is_calibrated())
     - "total_resolved": int (somme des samples)
     - "worst_bucket": le bucket avec la plus grosse error (ou None)

Utilise structured logging (logger = logging.getLogger(__name__)).
Pas de magic numbers — le seuil 10 samples doit etre une constante MIN_BUCKET_SAMPLES = 10.
Type hints stricts partout. Docstrings courtes (une ligne).
```

---

## PROMPT 2 — tests/test_calibration.py

```
Cree tests/test_calibration.py — tests unitaires pour core/calibration.py.

Le module a 3 fonctions : apply_calibration_adjustment, is_calibrated, get_calibration_report.
Il utilise CalibrationBucket de infra.types (frozen dataclass avec : bucket_start, bucket_end,
predicted_prob, actual_win_rate, num_samples, error).

Ecris 12-15 tests couvrant :

apply_calibration_adjustment :
- Ajustement correct quand bucket a >= 10 samples (ex: raw=0.7, actual=0.8, predicted=0.65 -> +0.15)
- Pas d'ajustement si bucket < 10 samples -> retourne raw_prob
- Clamp a 0.01 si ajustement negatif extreme
- Clamp a 0.99 si ajustement positif extreme
- Bucket vide (liste vide) -> retourne raw_prob
- Probabilite aux limites (0.0, 0.95, 1.0) -> trouve le bon bucket

is_calibrated :
- Tous les buckets calibres (error <= 0.08) -> True
- Un bucket mal calibre -> False
- Aucun bucket avec >= 10 samples -> False (pas assez de donnees)
- max_error custom (0.10) fonctionne
- Liste vide -> False

get_calibration_report :
- Mock db.compute_calibration() -> verifie structure du dict retourne
- Verifie que worst_bucket est correct
- Verifie total_resolved = somme des num_samples

Fixtures : creer des CalibrationBucket helper pour construire des buckets facilement.
Mocker infra.db.compute_calibration avec @patch.
Ne JAMAIS appeler de vraie DB — tout mocke.
```

---

## PROMPT 3 — Ameliorations scorer (prompts par categorie)

Prerequis : prompt 4 fait avant celui-ci.

```
Ameliore core/scorer.py — ajoute des system prompts specialises par categorie de marche.

Actuellement il y a un seul SCORER_SYSTEM_PROMPT generique. On veut des prompts adaptes
pour mieux scorer chaque type de marche.

1. Cree un dict CATEGORY_PROMPTS: dict[str, str] avec des prompts pour :
   - "politics" : focus sur sondages, historique electoral, dynamique institutionnelle
   - "science" : focus sur publications peer-reviewed, consensus scientifique, timeline R&D
   - "sports_outcome" : focus sur stats joueurs/equipes, blessures, form recente, cotes bookmakers
   - "geopolitics" : focus sur relations internationales, sanctions, precedents historiques
   - "default" : le prompt actuel (fallback)

2. Modifie score_market() pour :
   - Recuperer la categorie du marche (market.category existe deja dans MarketData)
   - Selectionner le prompt approprie depuis CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["default"])
   - Logger quelle categorie de prompt est utilisee

3. Ajoute le mode "second opinion" :
   - Nouvelle fonction get_second_opinion(market, news_context, first_result: ScoringResult) -> ScoringResult | None
   - Appelle Claude une 2e fois avec un prompt different : "You are reviewing another analyst's assessment..."
   - Si |first.probability - second.probability| > 0.15 : logger un WARNING "divergence_detected"
   - Retourner le second ScoringResult

4. Ne PAS changer la signature de score_and_evaluate(). Le second opinion est optionnel,
   active par un flag dans config.py : ENABLE_SECOND_OPINION = False (off par defaut).

Garder temperature=0.0 pour reproductibilite.
Ne pas toucher a compute_edge() ni build_trading_signal().
Structured logging partout.
```

---

## PROMPT 4 — Validation Pydantic + tracking latence scorer

```
Ameliore core/scorer.py — ajoute validation Pydantic et tracking de latence/tokens.

1. Validation Pydantic des reponses Claude :
   - Cree un modele Pydantic (BaseModel) ScorerResponse avec :
     - probability: float (ge=0.0, le=1.0)
     - confidence: int (ge=0, le=10)
     - reasoning: str (min_length=10)
     - key_factors: list[str] (min_length=1)
   - Remplace le parsing JSON manuel dans score_market() par ScorerResponse.model_validate(parsed_json)
   - Les ValidationError doivent etre logges et retourner None (comme actuellement pour les erreurs JSON)

2. Tracking latence + tokens :
   - Mesurer le temps de chaque appel Claude (time.monotonic() avant/apres)
   - Extraire input_tokens et output_tokens depuis response.usage
   - Logger apres chaque appel : logger.info("scorer_api_call", extra={
       "market_id": market.market_id,
       "latency_ms": round(elapsed * 1000),
       "input_tokens": usage.input_tokens,
       "output_tokens": usage.output_tokens,
       "model": MODEL,
       "category": market.category
     })

3. Ajouter pydantic dans pyproject.toml si pas deja present (verifier d'abord).

Ne casse aucun test existant — adapter les mocks si necessaire pour que les 15 tests passent toujours.
Lancer pytest tests/test_scorer.py -v a la fin pour verifier.
```

---

## PROMPT 5 — Ameliorations fetcher

```
Ameliore core/fetcher.py — ajoute prix historique 24h, profondeur orderbook, et cache TTL.

1. Prix historique 24h (momentum) :
   - Nouvelle fonction fetch_price_history(market_id: str) -> dict | None
   - Appelle l'endpoint Gamma /prices/history?market={id}&interval=1h&fidelity=24
   - Retourne {"price_24h_ago": float, "current_price": float, "momentum": float}
   - momentum = current_price - price_24h_ago (positif = trending YES)
   - Timeout 5s, retourne None si erreur
   - Ajouter le momentum dans MarketData si possible, sinon le retourner separement

2. Profondeur du carnet d'ordres (liquidite) :
   - Nouvelle fonction fetch_orderbook_depth(token_id: str) -> dict | None
   - Appelle l'endpoint CLOB /book?token_id={id}
   - Calcule la liquidite a +/-2% du mid price (somme des sizes dans cette range)
   - Retourne {"bid_depth_2pct": float, "ask_depth_2pct": float, "total_liquidity": float}
   - Timeout 5s, retourne None si erreur

3. Cache TTL :
   - Utilise functools.lru_cache ou un dict simple avec timestamp
   - Cache les resultats de fetch_raw_markets() pendant TTL = 300s (5 min, configurable dans config.py)
   - Cache les resultats de fetch_price_history() pendant TTL = 600s (10 min)
   - Fonction clear_cache() pour les tests et le reset manuel
   - Logger cache hit/miss

Ajouter CACHE_TTL_MARKETS = 300 et CACHE_TTL_PRICES = 600 dans infra/config.py.
Ne PAS modifier les signatures existantes de get_tradeable_markets() ou filter_markets().
Structured logging, type hints stricts.
Lancer pytest tests/test_fetcher.py -v a la fin.
```

---

## PROMPT 6 — Tests complets (fetcher + scorer)

Prerequis : prompts 3, 4, 5 faits avant.

```
Mets a jour les tests pour couvrir les nouvelles fonctionnalites du fetcher et scorer.

tests/test_fetcher.py — ajouter 8-10 tests :
- fetch_price_history : reponse valide, timeout, format inattendu
- fetch_orderbook_depth : reponse valide, pas de liquidite a +/-2%, timeout
- Cache TTL : verifier que 2 appels rapides ne font qu'un seul HTTP call
- clear_cache() : verifier que le cache est bien vide
- Verifier que get_tradeable_markets() fonctionne toujours sans regression

tests/test_scorer.py — ajouter 8-10 tests :
- CATEGORY_PROMPTS : verifier que chaque categorie a un prompt
- score_market avec categorie "politics" utilise le bon prompt (mock verify)
- score_market avec categorie inconnue utilise le prompt default
- Validation Pydantic : champ manquant -> None
- Validation Pydantic : probability hors range -> None
- Validation Pydantic : confidence hors range -> None
- get_second_opinion : divergence > 0.15 -> WARNING logge
- get_second_opinion : divergence < 0.15 -> pas de WARNING
- Tracking latence : verifier que le log contient latency_ms et tokens

Tout mocke, aucun appel API reel. Fixtures propres.
Lancer pytest tests/ -v a la fin pour verifier que TOUS les tests passent (anciens + nouveaux).
```

---

## Checklist finale

Apres les 6 prompts, verifie tout d'un coup :

```bash
pytest tests/ -v
mypy core/ infra/ --strict
ruff check core/ infra/
```

Si tout est vert, commit et push sur la branche Edouard.
