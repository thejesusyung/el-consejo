"""Thin wrapper around the Bedrock Runtime Converse API.

Model IDs are cross-region inference profiles (us. prefix) so calls can route
across us-east-1 / us-east-2 / us-west-2 without extra config. All overridable
via env vars for easy A/B swapping.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

import boto3

HAIKU_MODEL_ID = os.getenv("BEDROCK_HAIKU_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
SONNET_MODEL_ID = os.getenv("BEDROCK_SONNET_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
TITAN_EMBED_MODEL_ID = os.getenv("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
REGION = os.getenv("AWS_REGION", "us-east-1")


@lru_cache(maxsize=1)
def _runtime():
    return boto3.client("bedrock-runtime", region_name=REGION)


def converse(
    model_id: str,
    system: str,
    user: str,
    max_tokens: int = 800,
    temperature: float = 0.7,
) -> str:
    resp = _runtime().converse(
        modelId=model_id,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": user}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
    )
    return resp["output"]["message"]["content"][0]["text"].strip()


def haiku(system: str, user: str, **kw: Any) -> str:
    return converse(HAIKU_MODEL_ID, system, user, **kw)


def sonnet(system: str, user: str, **kw: Any) -> str:
    return converse(SONNET_MODEL_ID, system, user, **kw)


def embed(text: str) -> list[float]:
    resp = _runtime().invoke_model(
        modelId=TITAN_EMBED_MODEL_ID,
        body=json.dumps({"inputText": text, "dimensions": 256, "normalize": True}),
    )
    return json.loads(resp["body"].read())["embedding"]
