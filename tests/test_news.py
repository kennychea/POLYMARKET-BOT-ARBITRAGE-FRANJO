"""Tests for core/news.py — Perplexity + RSS news context aggregator.

All external HTTP calls are mocked. Zero real API calls.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import requests

from core.news import build_news_context, fetch_perplexity_context, fetch_rss_headlines

_QUESTION = "Will X happen by 2026-06-01?"

# ── Valid RSS XML fixture ────────────────────────────────────────────────────

_VALID_RSS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test</title>
    <item>
      <title>Big event confirmed</title>
      <pubDate>Wed, 18 Jun 2025 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Another development</title>
      <pubDate>Tue, 17 Jun 2025 08:30:00 GMT</pubDate>
    </item>
    <item>
      <title>Third headline</title>
      <pubDate>Mon, 16 Jun 2025 15:45:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


# ── fetch_perplexity_context tests ───────────────────────────────────────────


@patch("core.news.requests.post")
def test_perplexity_success(mock_post: MagicMock) -> None:
    """Valid API response → returns research text."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "Research summary here."}}]
    }
    mock_post.return_value = mock_resp

    result = fetch_perplexity_context(_QUESTION)

    assert result == "Research summary here."
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert "Authorization" in call_kwargs.kwargs.get("headers", call_kwargs[1].get("headers", {}))


@patch("core.news.requests.post")
def test_perplexity_api_error(mock_post: MagicMock) -> None:
    """API HTTP error → returns empty string."""
    mock_post.side_effect = requests.HTTPError("500 Server Error")

    result = fetch_perplexity_context(_QUESTION)

    assert result == ""


@patch("core.news.requests.post")
def test_perplexity_timeout(mock_post: MagicMock) -> None:
    """Timeout → returns empty string."""
    mock_post.side_effect = requests.Timeout("Connection timed out")

    result = fetch_perplexity_context(_QUESTION)

    assert result == ""


# ── fetch_rss_headlines tests ────────────────────────────────────────────────


@patch("core.news.requests.get")
def test_rss_valid_xml(mock_get: MagicMock) -> None:
    """Valid RSS XML → returns list of formatted headlines."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = _VALID_RSS_XML
    mock_get.return_value = mock_resp

    result = fetch_rss_headlines(_QUESTION, max_results=5)

    assert len(result) == 3
    assert "Big event confirmed" in result[0]
    assert "Jun 18" in result[0]
    assert "Another development" in result[1]


@patch("core.news.requests.get")
def test_rss_malformed_xml(mock_get: MagicMock) -> None:
    """Malformed XML → returns empty list."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.text = "<<<not xml at all>>>"
    mock_get.return_value = mock_resp

    result = fetch_rss_headlines(_QUESTION)

    assert result == []


@patch("core.news.requests.get")
def test_rss_timeout(mock_get: MagicMock) -> None:
    """Timeout → returns empty list."""
    mock_get.side_effect = requests.Timeout("Connection timed out")

    result = fetch_rss_headlines(_QUESTION)

    assert result == []


# ── build_news_context tests ────────────────────────────────────────────────


@patch("core.news.fetch_rss_headlines")
@patch("core.news.fetch_perplexity_context")
def test_build_both_succeed(mock_perplexity: MagicMock, mock_rss: MagicMock) -> None:
    """Both succeed → string contains both sections."""
    mock_perplexity.return_value = "Deep research findings."
    mock_rss.return_value = ["Headline A (Jun 18)", "Headline B (Jun 17)"]

    result = build_news_context(_QUESTION)

    assert "=== PERPLEXITY RESEARCH ===" in result
    assert "Deep research findings." in result
    assert "=== RECENT HEADLINES ===" in result
    assert "- Headline A (Jun 18)" in result
    assert "- Headline B (Jun 17)" in result


@patch("core.news.fetch_rss_headlines")
@patch("core.news.fetch_perplexity_context")
def test_build_perplexity_fails_rss_works(
    mock_perplexity: MagicMock, mock_rss: MagicMock
) -> None:
    """Perplexity fails, RSS works → headlines only."""
    mock_perplexity.return_value = ""
    mock_rss.return_value = ["Headline A (Jun 18)"]

    result = build_news_context(_QUESTION)

    assert "PERPLEXITY RESEARCH" not in result
    assert "=== RECENT HEADLINES ===" in result
    assert "- Headline A (Jun 18)" in result


@patch("core.news.fetch_rss_headlines")
@patch("core.news.fetch_perplexity_context")
def test_build_both_fail(mock_perplexity: MagicMock, mock_rss: MagicMock) -> None:
    """Both fail → returns fallback message."""
    mock_perplexity.return_value = ""
    mock_rss.return_value = []

    result = build_news_context(_QUESTION)

    assert result == "No news context available."


@patch("core.news.fetch_rss_headlines")
@patch("core.news.fetch_perplexity_context")
def test_build_runs_in_parallel(
    mock_perplexity: MagicMock, mock_rss: MagicMock
) -> None:
    """Both sources execute in parallel — total time < sum of individual delays."""
    def slow_perplexity(q: str) -> str:
        time.sleep(0.1)
        return "Research text."

    def slow_rss(q: str) -> list[str]:
        time.sleep(0.1)
        return ["Headline (Jun 18)"]

    mock_perplexity.side_effect = slow_perplexity
    mock_rss.side_effect = slow_rss

    start = time.monotonic()
    result = build_news_context(_QUESTION)
    elapsed = time.monotonic() - start

    assert "Research text." in result
    assert "Headline (Jun 18)" in result
    # If parallel, ~0.1s. If sequential, ~0.2s. Allow generous margin.
    assert elapsed < 0.5, f"Took {elapsed:.2f}s — expected parallel execution"
