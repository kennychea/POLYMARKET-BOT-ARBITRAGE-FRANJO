# Debugging Protocol

## Quand un bug est signalé

1. **Reproduire** — lancer le test ou la commande qui fail. Ne jamais supposer la cause.
2. **Lire les logs** — chercher dans les logs structurés (`extra={}`) les événements autour du timestamp.
3. **Isoler** — le bug est dans core/, execution/, infra/, ou pipeline/ ? Suivre le data flow.
4. **Cause racine** — remonter la chaîne. Un symptôme dans portfolio.py peut avoir sa cause dans sizing.py.
5. **Fix minimal** — toucher le minimum de code. Pas de refactor opportuniste pendant un fix.
6. **Test** — ajouter un test qui reproduit le bug AVANT de fixer, puis vérifier qu'il passe après.
7. **Lesson** — ajouter dans `tasks/lessons.md` : `[date] | description | règle`

## Patterns de debug fréquents

### API externe renvoie une erreur
- Vérifier le status_code et le body de la réponse
- Vérifier les headers (rate limit, auth)
- Tester avec un curl/requests.get isolé dans un sous-agent
- Ne JAMAIS changer la logique métier pour compenser une API cassée

### Test qui fail après un refactor
- `git diff` pour voir exactement ce qui a changé
- Vérifier que les mocks correspondent à la nouvelle signature
- Vérifier les imports (cross-import interdit entre core/ et execution/)
- Lancer `mypy --strict` pour détecter les incompatibilités de types

### Données incohérentes en DB
- Vérifier le schéma dans `infra/db.py`
- Tester avec SQLite en mémoire (":memory:")
- Vérifier les types de colonnes (TEXT vs REAL vs INTEGER)
- Ne JAMAIS modifier le schéma sans migration

### Pipeline qui ne produit pas de signaux
- Vérifier les filtres dans `infra/config.py` (volume, spread, days_to_resolution)
- Vérifier que le scorer reçoit bien le news_context
- Vérifier edge_net > 0.05 ET confidence >= 6
- Logger les valeurs intermédiaires à chaque étape

## Anti-patterns

- NE PAS ajouter des try/except partout pour "cacher" les erreurs
- NE PAS modifier les thresholds pour faire passer un test
- NE PAS supposer que le problème est dans le dernier fichier modifié
- NE PAS lancer un refactor pendant un debug — fix d'abord, refactor ensuite
- NE PAS commit un fix sans test associé
