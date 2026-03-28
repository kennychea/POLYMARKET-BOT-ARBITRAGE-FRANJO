"""News context aggregator — Perplexity research + RSS headlines.

Entry point: build_news_context(question) → str
Feeds the scorer with relevant context; does NOT make trading decisions.
"""
from __future__ import annotations

import logging
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import requests

import infra.config as cfg

logger = logging.getLogger(__name__)

_PERPLEXITY_URL = "https://api.perplexity.ai/chat/completions"
_PERPLEXITY_MODEL = "sonar"
_PERPLEXITY_TIMEOUT = 10
_PERPLEXITY_MAX_TOKENS = 500

_RSS_BASE = "https://news.google.com/rss/search"
_RSS_TIMEOUT = 10
_RSS_MAX_RESULTS = 5

_EXECUTOR_TIMEOUT = 15

_PERPLEXITY_SYSTEM_PROMPT = (
    "You are a research assistant. Given a prediction market question, "
    "provide a concise factual summary of the most relevant recent news and data. "
    "Focus on facts that would help estimate the probability of the event. "
    "No opinions, no speculation. Max 3 paragraphs."
)


def fetch_perplexity_context(
    question: str, max_tokens: int = _PERPLEXITY_MAX_TOKENS
) -> str:
    """Fetch research context from Perplexity API for a market question.

    Returns empty string on any error.
    """
    try:
        response = requests.post(
            _PERPLEXITY_URL,
            headers={
                "Authorization": f"Bearer {cfg.PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": _PERPLEXITY_MODEL,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": _PERPLEXITY_SYSTEM_PROMPT},
                    {"role": "user", "content": question},
                ],
            },
            timeout=_PERPLEXITY_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return str(data["choices"][0]["message"]["content"])
    except Exception as e:
        logger.warning(
            "perplexity_failed",
            extra={"question": question[:60], "error": str(e)},
        )
        return ""


def _parse_pub_date(pub_date_str: str) -> str:
    """Parse RSS pubDate into 'Mon DD' format. Returns raw string on failure."""
    # RFC 822 format: "Wed, 18 Jun 2025 12:00:00 GMT"
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(pub_date_str.strip(), fmt)
            return dt.strftime("%b %d")
        except ValueError:
            continue
    return pub_date_str.strip()[:6]


def fetch_rss_headlines(
    question: str, max_results: int = _RSS_MAX_RESULTS
) -> list[str]:
    """Fetch recent headlines from Google News RSS for a market question.

    Returns empty list on any error.
    """
    try:
        url = f"{_RSS_BASE}?q={urllib.parse.quote(question)}&hl=en"
        response = requests.get(url, timeout=_RSS_TIMEOUT)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        headlines: list[str] = []

        for item in root.iter("item"):
            if len(headlines) >= max_results:
                break
            title_el = item.find("title")
            pub_date_el = item.find("pubDate")
            if title_el is None or title_el.text is None:
                continue
            title = title_el.text.strip()
            if pub_date_el is not None and pub_date_el.text:
                date_str = _parse_pub_date(pub_date_el.text)
                headlines.append(f"{title} ({date_str})")
            else:
                headlines.append(title)

        return headlines
    except Exception as e:
        logger.warning(
            "rss_failed",
            extra={"question": question[:60], "error": str(e)},
        )
        return []


def build_news_context(question: str) -> str:
    """Build combined news context from Perplexity + RSS in parallel.

    Returns a formatted string with both sections, skipping any that fail.
    Returns 'No news context available.' if both sources fail.
    """
    perplexity_text = ""
    headlines: list[str] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_perplexity = executor.submit(fetch_perplexity_context, question)
        future_rss = executor.submit(fetch_rss_headlines, question)

        futures: dict[Future[Any], str] = {
            future_perplexity: "perplexity",
            future_rss: "rss",
        }

        for future in as_completed(futures, timeout=_EXECUTOR_TIMEOUT):
            label = futures[future]
            try:
                result = future.result()
                if label == "perplexity":
                    perplexity_text = result
                else:
                    headlines = result
            except Exception as e:
                logger.warning(
                    f"{label}_executor_error",
                    extra={"question": question[:60], "error": str(e)},
                )

    sections: list[str] = []
    if perplexity_text:
        sections.append(f"=== PERPLEXITY RESEARCH ===\n{perplexity_text}")
    if headlines:
        formatted = "\n".join(f"- {h}" for h in headlines)
        sections.append(f"=== RECENT HEADLINES ===\n{formatted}")

    logger.info(
        "news_context_built",
        extra={
            "question": question[:60],
            "has_perplexity": bool(perplexity_text),
            "headlines_count": len(headlines),
        },
    )

    if not sections:
        return "No news context available."
    return "\n\n".join(sections)


# ── CLI helper ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    question = (
        sys.argv[1] if len(sys.argv) > 1
        else "Will Trump be indicted before July 2026?"
    )
    print(build_news_context(question))
