"""OpenRouter fallback client — drop-in replacement for bedrock_client.

Used when Bedrock quotas are unavailable. Activated by setting
LLM_BACKEND=openrouter and OPENROUTER_API_KEY in the environment.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

HAIKU_MODEL_ID = os.getenv(
    "OPENROUTER_HAIKU_MODEL_ID", "minimax/minimax-m2.5:free"
)
SONNET_MODEL_ID = os.getenv(
    "OPENROUTER_SONNET_MODEL_ID", "inclusionai/ling-2.6-1t:free"
)


MAX_RETRIES = 7
BASE_DELAY = 3.0


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

    for attempt in range(MAX_RETRIES):
        req = urllib.request.Request(
            OPENROUTER_BASE_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < MAX_RETRIES - 1:
                delay = BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            raise

    raise RuntimeError("unreachable")


def converse(model_id: str, system: str, user: str, max_tokens: int = 800, temperature: float = 0.7) -> str:
    return _call(model_id, system, user, max_tokens, temperature)


def haiku(system: str, user: str, **kw: Any) -> str:
    return converse(HAIKU_MODEL_ID, system, user, **kw)


def sonnet(system: str, user: str, **kw: Any) -> str:
    return converse(SONNET_MODEL_ID, system, user, **kw)


def embed(text: str) -> list[float]:
    raise NotImplementedError("Embeddings not available via OpenRouter free tier")
