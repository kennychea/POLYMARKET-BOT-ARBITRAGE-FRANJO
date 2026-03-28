# Lessons Learned — Polymarket Agent

Format: [date] | what went wrong / decision made | rule to avoid it / apply it

## Architecture & Design Decisions

[2026-03] | Choix quarter Kelly (0.25) au lieu de full Kelly | Full Kelly est trop agressif pour un petit bankroll ($50-100). Quarter Kelly réduit la variance et le risque de ruin. NE JAMAIS augmenter le Kelly fraction sans 2 mois de data profitables.

[2026-03] | Edge informationnel vs edge vitesse | On cible les marchés niche (volume 1K-50K) où les gros bots ne jouent pas. NE JAMAIS scorer les marchés crypto_price — ils sont trop efficients.

[2026-03] | Limit orders only, jamais market orders | Les market orders sur Polymarket CLOB ont un slippage imprévisible. Toujours GTC limit orders avec slippage cap 2%.

[2026-03] | Circuit breaker à -20% sur 7 jours | Évite la spirale de pertes. Doit déclencher STOP automatique + alerte Telegram. Ne JAMAIS override le circuit breaker programmatiquement.

[2026-03] | Séparation core/ vs execution/ via infra/types.py | Les deux modules communiquent uniquement via les dataclasses gelées. Aucun import croisé. Ça permet à Edouard et Franjo de travailler en parallèle sans conflits.

## Calibration & Scoring

[2026-03] | Ne jamais ancrer le scoring au prix marché | Le prompt du scorer ne doit JAMAIS contenir le prix actuel du marché. Claude doit estimer P(event) indépendamment, puis on compare.

[2026-03] | Confidence < 5 = "données insuffisantes" → skip | Si le scorer n'a pas assez de contexte news, il doit signaler data_quality="low" et confidence bas. Ne pas trader dans le doute.

[2026-03] | Calibration target < 0.08 avant live | Au moins 100 signaux en paper trading avec une erreur de calibration par bucket < 8% avant de risquer de l'argent réel.

## Infrastructure

[2026-03] | Tous les thresholds dans infra/config.py | Zéro magic number dans le code. Même les délais (rate limits, timeouts) passent par config. Facilite le tuning sans toucher à la logique.

[2026-03] | Mock ALL external APIs dans les tests | Anthropic, Polymarket Gamma, Perplexity, Telegram — tout est mocké. Aucun test ne doit faire un appel réseau réel.

[2026-03] | Structured logging everywhere | `logger.info("event_name", extra={"key": val})` — jamais print(). Les logs structurés permettent de débugger en production et de construire des métriques.

## Process

[2026-03] | Toujours planifier dans tasks/todo.md avant d'implémenter | Écrire le plan évite les allers-retours. Pour les tâches non triviales (3+ étapes), passer en mode plan.

[2026-03] | Sauvegarder l'état avant compaction de contexte | Si le contexte approche de la limite, dump l'état dans tasks/todo.md AVANT que la compaction ne supprime des infos critiques.

[2026-03] | Un sous-agent par tâche | Garder le contexte principal propre. Les explorations longues (debug, recherche API) se font dans un sous-agent dédié.
