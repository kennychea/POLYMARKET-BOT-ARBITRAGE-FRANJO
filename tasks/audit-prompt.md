# Prompt d'audit — À coller dans VS Code Claude Code

```
Tu es un auditeur senior. On vient d'optimiser massivement le setup .claude/ de ce projet.
Ta mission : vérification complète de TOUT ce qui a été ajouté/modifié.
Tu dois trouver CHAQUE erreur, incohérence, ou risque. Sois impitoyable.

## CONTEXTE
Les fichiers suivants ont été créés ou modifiés aujourd'hui (2026-03-28) :

### Créés :
- docs/architecture.md (extrait depuis l'ancien CLAUDE.md)
- .claude/skills/debugging.md
- .claude/skills/claude-api-patterns.md
- .claude/skills/streamlit-dashboard.md
- .claude/agents/dashboard.md
- .claude/commands/test.md
- .claude/commands/check.md
- .claude/commands/status.md
- .claude/commands/review.md
- .claude/commands/fix.md
- .claude/commands/implement.md
- .github/workflows/ci.yml
- .pre-commit-config.yaml
- Makefile
- data/.gitkeep

### Modifiés :
- CLAUDE.md (slimmed de 296 → 121 lignes)
- tasks/lessons.md (rempli avec 14 leçons rétroactives)
- tasks/todo.md (mis à jour)
- .claude/settings.json (permissions allow/deny complètes)
- .claude/settings.local.json (nettoyé → {})
- .claude/agents/reviewer.md (checklist hiérarchisée + Bash tool ajouté)
- .claude/agents/tester.md (état des tests mis à jour)
- .claude/agents/scorer.md (ajout claude-api-patterns.md dans skills)
- .claude/skills/SKILLS.md (index complet : 9 skills, 7 agents, 7 commands)
- .claude/commands/spec.md (retiré AskUserQuestion, reformulé)
- pyproject.toml (ajout pre-commit dep, ruff.lint, isort, coverage config)
- .gitignore (ajout data/*.db, data/*.db-journal, data/*.db-wal)

### Supprimé :
- pourclaude/ (ancien backup obsolète de .claude/)

## ÉTAPES D'AUDIT

### Phase 1 : Lire les fichiers de référence
1. Lire infra/config.py — c'est la source de vérité pour les thresholds et l'import pattern
2. Lire infra/types.py — c'est la source de vérité pour les dataclasses
3. Lire core/scorer.py — vérifier comment il importe config et appelle l'API Claude

### Phase 2 : Valider chaque fichier modifié/créé
Pour CHAQUE fichier listé ci-dessus :
1. Lire le fichier complet
2. Vérifier la syntaxe (YAML, JSON, TOML, Markdown, Python, Makefile)
3. Cross-checker les valeurs avec infra/config.py (thresholds, noms de variables, import patterns)
4. Cross-checker les références à d'autres fichiers (est-ce que le fichier cible existe ?)
5. Chercher les incohérences avec le reste du projet

### Phase 3 : Scans automatisés
Lancer ces commandes et reporter les résultats :

```bash
# 1. Bad patterns dans .claude/
grep -rn 'CONFIG\[' .claude/
grep -rn 'AskUserQuestion' .claude/
grep -rn 'pourclaude' .
grep -rn 'from infra.config import CONFIG' .claude/

# 2. Validation JSON
python -c "import json; json.load(open('.claude/settings.json')); print('settings.json: VALID')"

# 3. Validation TOML
python -c "import tomllib; tomllib.load(open('pyproject.toml','rb')); print('pyproject.toml: VALID')"

# 4. Validation YAML
python -c "
import yaml
for f in ['.pre-commit-config.yaml', '.github/workflows/ci.yml']:
    yaml.safe_load(open(f))
    print(f'{f}: VALID')
"

# 5. Check que tous les fichiers référencés existent
for f in infra/config.py infra/types.py infra/db.py infra/telegram.py \
         core/fetcher.py core/news.py core/scorer.py \
         execution/sizing.py execution/clob.py execution/orders.py execution/portfolio.py \
         pipeline/orchestrator.py \
         tasks/todo.md tasks/lessons.md \
         docs/architecture.md data/.gitkeep .specs/; do
  test -e "$f" && echo "✅ $f" || echo "❌ MISSING: $f"
done

# 6. Check permissions completeness
python -c "
import json
d = json.load(open('.claude/settings.json'))
required = ['Glob(*)', 'Grep(*)', 'Read(*)', 'Write(*)', 'Edit(*)']
allow = d['permissions']['allow']
for r in required:
    print(f'  {r}: {\"✅\" if r in allow else \"❌ MISSING\"}')"

# 7. Check deny list
python -c "
import json
d = json.load(open('.claude/settings.json'))
deny = d['permissions']['deny']
dangerous = ['rm -rf', 'push --force', 'reset --hard', 'git clean', 'orchestrator --live']
for cmd in dangerous:
    found = any(cmd in d for d in deny)
    print(f'  {cmd}: {\"✅ blocked\" if found else \"❌ NOT BLOCKED\"}')"

# 8. Run actual tests
pytest tests/ -v --tb=short

# 9. Run type check
mypy core/ execution/ infra/ pipeline/ --strict

# 10. Run lint
ruff check core/ execution/ infra/ pipeline/
```

### Phase 4 : Rapport final
Produis un rapport structuré :

```
## RÉSULTATS D'AUDIT

### BLOQUEURS (empêchent le fonctionnement)
- [fichier:ligne] description du problème

### WARNINGS (à corriger mais pas bloquant)
- [fichier:ligne] description

### VÉRIFICATIONS PASSÉES
- [catégorie] détail

### TESTS
- pytest: X passed / Y failed
- mypy: clean / N errors
- ruff: clean / N issues

### VERDICT FINAL
READY / NOT READY — avec justification
```

Sois exhaustif. Ne saute aucun fichier. Si tout est clean, dis-le clairement.
```
