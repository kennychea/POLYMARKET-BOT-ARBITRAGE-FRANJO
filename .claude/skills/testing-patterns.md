# Testing Patterns for This Project

## General rules
- All tests use pytest
- Mock external APIs (Anthropic, Polymarket, Perplexity) — never make real calls
- Use in-memory SQLite (":memory:") for DB tests
- tests/conftest.py seeds dummy env vars before collection

## Mocking patterns
```python
# Mock Anthropic client
from unittest.mock import MagicMock, patch

@patch("core.scorer.anthropic.Anthropic")
def test_scorer(mock_client):
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"probability": 0.65, ...}')]
    mock_client.return_value.messages.create.return_value = mock_response

# Mock requests (for fetcher, news)
@patch("core.fetcher.requests.Session.get")
def test_fetcher(mock_get):
    mock_get.return_value.json.return_value = {"data": [...]}
    mock_get.return_value.status_code = 200
```

## What to test
- Pure logic functions: edge computation, kelly sizing, filters
- JSON parsing: valid → dataclass, invalid → None
- Error handling: API timeout → graceful fallback, never crash
- Threshold enforcement: below min_edge → not tradeable

## What NOT to test
- External API behavior (mock it)
- Telegram delivery (mock requests.post)
- Exact log messages (test behavior, not strings)