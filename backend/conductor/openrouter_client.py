"""OpenRouter fallback client — drop-in replacement for bedrock_client.

Used when Bedrock quotas are unavailable. Activated by setting
LLM_BACKEND=openrouter and OPENROUTER_API_KEY in the environment.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

HAIKU_MODEL_ID = os.getenv(
    "OPENROUTER_HAIKU_MODEL_ID", "google/gemma-4-31b-it:free"
)
SONNET_MODEL_ID = os.getenv(
    "OPENROUTER_SONNET_MODEL_ID", "inclusionai/ling-2.6-1t:free"
)


def _call(model_id: str, system: str, user: str, max_tokens: int, temperature: float) -> str:
    body = json.dumps({
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }).encode()

    req = urllib.request.Request(
        OPENROUTER_BASE_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())

    return data["choices"][0]["message"]["content"].strip()


def converse(model_id: str, system: str, user: str, max_tokens: int = 800, temperature: float = 0.7) -> str:
    return _call(model_id, system, user, max_tokens, temperature)


def haiku(system: str, user: str, **kw: Any) -> str:
    return converse(HAIKU_MODEL_ID, system, user, **kw)


def sonnet(system: str, user: str, **kw: Any) -> str:
    return converse(SONNET_MODEL_ID, system, user, **kw)


def embed(text: str) -> list[float]:
    raise NotImplementedError("Embeddings not available via OpenRouter free tier")
