"""LLM provider switch — routes to Bedrock or OpenRouter based on LLM_BACKEND env var."""
from __future__ import annotations

import os

_backend = os.getenv("LLM_BACKEND", "bedrock").lower()

if _backend == "openrouter":
    from . import openrouter_client as _client
else:
    from . import bedrock_client as _client  # type: ignore[no-redef]

haiku = _client.haiku
sonnet = _client.sonnet
embed = _client.embed
converse = _client.converse
