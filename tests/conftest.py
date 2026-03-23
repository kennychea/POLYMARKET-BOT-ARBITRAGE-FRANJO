"""pytest configuration — seed required env vars before any module import.

config.py calls _require() at module level, so env vars must exist before
infra.config is imported (i.e., before collection starts).
"""
import os

_TEST_DEFAULTS = {
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "POLYMARKET_API_KEY": "test-poly-key",
    "POLYMARKET_PRIVATE_KEY": "0xdeadbeef",
    "PERPLEXITY_API_KEY": "test-perplexity-key",
    "TELEGRAM_BOT_TOKEN": "test-tg-token",
    "TELEGRAM_CHAT_ID": "123456789",
    "DB_PATH": ":memory:",
}

for _key, _val in _TEST_DEFAULTS.items():
    os.environ.setdefault(_key, _val)
