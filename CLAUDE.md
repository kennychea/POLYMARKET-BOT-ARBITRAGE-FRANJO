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

### 7. Gestion du contexte
- Le contexte sera automatiquement compacté quand il approche de la limite
- Ne JAMAIS arrêter une tâche prématurément à cause du budget de tokens
- Avant compaction : sauvegarder l'état dans tasks/todo.md
- Utiliser des sous-agents pour les explorations longues
- Pour les questions rapides sans rapport : utiliser un sous-agent

## PRINCIPES FONDAMENTAUX

- Simplicité d'abord — toucher un minimum de code
- Pas de paresse — causes racines uniquement, pas de fixes temporaires
- Ne jamais supposer — vérifier chemins, APIs, variables avant utilisation
- Demander une seule fois — une question en amont si nécessaire, ne jamais interrompre en cours de tâche
- Être explicite — Claude suit les instructions littéralement. Dire exactement ce qu'on veut
- Expliquer le pourquoi — « On utilise quarter Kelly PARCE QUE full Kelly est trop agressif pour un petit bankroll »
- Pas de raccourcis sur les exemples — vérifier qu'ils reflètent le comportement voulu

## CONTRATS GELÉS (NE PAS MODIFIER sans PR + accord des deux)

Voir `infra/types.py` pour les dataclasses complètes : TradingSignal, Position, ScoringResult, EdgeResult, OrderResult, CalibrationBucket.

## THRESHOLDS (NE PAS CHANGER sans discussion)

```python
MIN_EDGE_NET = 0.05              # 5% minimum après frais
MIN_CONFIDENCE = 6               # sur 10
KELLY_FRACTION = 0.25            # quarter Kelly
MAX_POSITION_PCT = 0.08          # 8% bankroll max par trade
MAX_SIMULTANEOUS_POSITIONS = 5
CYCLE_INTERVAL_SECONDS = 900     # 15 min
MIN_TRADE_SIZE = 5.0             # USDC minimum
POLYMARKET_FEE = 0.02            # 2% sur gains
```

## CE QU'IL NE FAUT PAS FAIRE

- NE PAS utiliser de market orders — limit only
- NE PAS hardcoder de threshold — tout depuis infra.config
- NE PAS commit .env ou un secret
- NE PAS ajouter de deps sans mettre à jour pyproject.toml
- NE PAS modifier TradingSignal/Position sans update all consumers
- NE PAS appeler de vraies APIs dans les tests — toujours mock
- NE PAS trader si confidence < 6 ou edge_net < 0.05
- NE PAS dépasser 5 positions simultanées
- NE PAS cross-importer entre core/ et execution/ — direction: core/ → infra/ ← execution/
- NE PAS utiliser print() — toujours logger avec structured logging
- NE PAS utiliser de magic numbers — tout dans infra/config.py

## COMMANDES RAPIDES

```bash
pytest tests/ -v                                    # Tests
mypy core/ execution/ infra/ pipeline/ --strict     # Type check
ruff check core/ execution/ infra/ pipeline/        # Lint
python -m pipeline.orchestrator --paper --once       # Un cycle paper
python -m core.scorer --market-id "xxx" --verbose    # Score un marché
```

## RÉFÉRENCES

- Architecture détaillée : `docs/architecture.md`
- État du projet : `tasks/todo.md`
- Leçons : `tasks/lessons.md`
- Skills : `.claude/skills/SKILLS.md`
- Contrats : `infra/types.py`
- Config : `infra/config.py`

## Compact Instructions

When compacting context, ALWAYS preserve:
- The full list of modified files in this session
- All test commands and their pass/fail results
- Current task from tasks/todo.md
- Any error messages or stack traces being debugged
- The contract interfaces (TradingSignal, Position)
- Current thresholds (MIN_EDGE_NET=0.05, MIN_CONFIDENCE=6, MIN_TRADE_SIZE=5.0)
