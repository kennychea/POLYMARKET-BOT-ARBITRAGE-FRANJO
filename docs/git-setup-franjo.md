# Setup Git — Franjo

## 1. Cloner le repo

```bash
git clone https://github.com/kennychea/POLYMARKET-BOT-ARBITRAGE-FRANJO.git
cd POLYMARKET-BOT-ARBITRAGE-FRANJO
```

## 2. Configurer ton identité git

```bash
git config user.name "Franjo"
git config user.email "ton-email@gmail.com"
```

## 3. Créer ta branche

```bash
git checkout -b franjo
```

## 4. Workflow quotidien

```bash
# Récupérer les derniers changements de main
git pull origin main

# Travailler, puis commit
git add <fichiers>
git commit -m "feat(exec): description du changement"

# Pousser sur ta branche
git push origin franjo
```

## 5. Pour merger dans main

Créer une **Pull Request** sur GitHub : `franjo → main`.
Jamais de push direct sur `main`.

## Conventions de commit

| Préfixe | Quand |
|---------|-------|
| `feat(exec):` | Nouveau code dans execution/ |
| `feat(infra):` | Nouveau code dans infra/ |
| `fix(exec):` | Bug fix dans execution/ |
| `test():` | Tests |
| `docs:` | Documentation |

## Fichiers de Franjo (ton domaine)

- `execution/sizing.py` — Kelly fractional + circuit breaker
- `execution/clob.py` — CLOB limit order wrapper
- `execution/orders.py` — Fill tracking
- `execution/portfolio.py` — Positions ouvertes
- `tests/test_sizing.py`, `tests/test_clob.py`
