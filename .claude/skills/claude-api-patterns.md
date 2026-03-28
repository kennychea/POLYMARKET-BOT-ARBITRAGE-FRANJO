# Claude API Patterns — Scoring Engine

## Configuration standard

Note : le **code de scoring** utilise Sonnet (coût/performance). L'**agent Claude Code** scorer tourne sur Opus (raisonnement complexe sur le code). Ce sont deux usages distincts.

```python
_MODEL = "claude-sonnet-4-20250514"  # Pour le scoring des marchés
TEMPERATURE = 0          # Déterministe pour la reproductibilité
MAX_TOKENS = 1024        # Suffisant pour un JSON structuré
```

## Pattern d'appel

```python
import anthropic
import infra.config as cfg

client = anthropic.Anthropic(api_key=cfg.ANTHROPIC_API_KEY)

response = client.messages.create(
    model=MODEL,
    max_tokens=MAX_TOKENS,
    temperature=0,
    messages=[{"role": "user", "content": prompt}],
)
raw_text = response.content[0].text
```

## Parsing du JSON

Claude renvoie parfois du JSON wrappé dans des fences markdown. Toujours strip :

```python
import json
import re

def _parse_scoring_response(raw: str) -> ScoringResult | None:
    """Parse Claude's JSON response, stripping markdown fences if present."""
    text = raw.strip()
    # Strip ```json ... ``` fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("scoring_parse_failed", extra={"raw_length": len(raw)})
        return None
```

## Retry policy

```python
MAX_RETRIES = 1  # Une seule retry
RETRY_DELAY = 2.0  # secondes

def call_with_retry(prompt: str) -> str | None:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.messages.create(...)
            return response.content[0].text
        except (anthropic.APIError, anthropic.APITimeoutError) as e:
            logger.warning("claude_api_error", extra={"attempt": attempt, "error": str(e)})
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return None
```

## Scoring prompt — Règles critiques

1. **NE JAMAIS inclure le prix marché actuel** dans le prompt → évite l'ancrage
2. **Toujours fournir le news_context** en entier — c'est notre edge informationnel
3. **Demander un JSON structuré** avec exactement ces champs :
   - `probability` (float 0.0-1.0)
   - `confidence` (int 0-10)
   - `reasoning` (string, max 200 mots)
   - `key_factors` (list[str], 3-5 facteurs)
   - `bear_case` (string)
   - `bull_case` (string)
   - `data_quality` ("high" | "medium" | "low")

4. **Inclure des exemples** de réponse attendue dans le prompt
5. **Demander explicitement** : "If data is insufficient, set confidence below 5"

## Validation de la réponse

```python
def validate_scoring(data: dict) -> bool:
    """Validate Claude's scoring output matches expected schema."""
    required = {"probability", "confidence", "reasoning", "key_factors",
                "bear_case", "bull_case", "data_quality"}
    if not required.issubset(data.keys()):
        return False
    if not (0.0 <= data["probability"] <= 1.0):
        return False
    if not (0 <= data["confidence"] <= 10):
        return False
    if data["data_quality"] not in ("high", "medium", "low"):
        return False
    return True
```

## Coûts et rate limits

- Sonnet : ~$3/M input, ~$15/M output tokens
- Un scoring prompt ~ 2K input + 500 output tokens → ~$0.01/scoring
- 100 scorings par cycle (max) → ~$1/cycle, ~$96/jour en continu
- Rate limit Anthropic Tier 1 : 50 RPM, 40K TPM → largement suffisant à 15min/cycle

## Anti-patterns

- NE PAS utiliser temperature > 0 pour le scoring (reproductibilité)
- NE PAS parser avec eval() — toujours json.loads()
- NE PAS ignorer data_quality="low" — si low, confidence doit être < 5
- NE PAS faire de scoring batch (un marché = un appel) — le contexte par marché est unique
- NE PAS cacher les erreurs de parsing — logger et retourner None
