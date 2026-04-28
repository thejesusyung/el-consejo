"""Single source of truth for AWS resource names and the Bedrock model IDs
that non-orchestrator scripts also need.

Everything env-var-overridable so a second deployment (e.g. a throwaway stack
for eval experiments) doesn't require code changes.
"""
from __future__ import annotations

import os

REGION = os.getenv("AWS_REGION", "us-east-1")

# Single DynamoDB table (single-table design: personas + sessions + eval + feedback).
TABLE_NAME = os.getenv("ELCONSEJO_TABLE", "elconsejo")

# Three buckets. In Phase 1 only ASSETS (portraits) is used.
BUCKET_ASSETS = os.getenv("ELCONSEJO_BUCKET_ASSETS", "elconsejo-assets")
BUCKET_AUDIO_IN = os.getenv("ELCONSEJO_BUCKET_AUDIO_IN", "elconsejo-audio-in")
BUCKET_AUDIO_OUT = os.getenv("ELCONSEJO_BUCKET_AUDIO_OUT", "elconsejo-audio-out")
BUCKET_TRANSCRIPTS = os.getenv("ELCONSEJO_BUCKET_TRANSCRIPTS", "elconsejo-transcripts")

SQS_CONDUCTOR_URL = os.getenv("ELCONSEJO_SQS_CONDUCTOR_URL", "")
SQS_EVAL_URL = os.getenv("ELCONSEJO_SQS_EVAL_URL", "")

# Set TTS_BACKEND=openrouter to use OpenRouter Gemini TTS instead of Polly.
TTS_BACKEND = os.getenv("TTS_BACKEND", "polly")
OPENROUTER_TTS_MODEL = os.getenv("OPENROUTER_TTS_MODEL", "google/gemini-2.5-flash-preview-tts")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

NOVA_CANVAS_MODEL_ID = os.getenv("BEDROCK_NOVA_CANVAS_MODEL_ID", "amazon.nova-canvas-v1:0")


def portrait_key(persona_key: str) -> str:
    return f"portraits/{persona_key}.png"
