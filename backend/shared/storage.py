"""DynamoDB read/write helpers for sessions + personas.

Single-table design keyed on (pk, sk):

  pk=PERSONA,       sk=<key>                  persona definitions
  pk=SESSION#<id>,  sk=META                   session metadata + status
  pk=SESSION#<id>,  sk=LINE#<idx3>#<role>     one conversation line (ordered by idx)
  pk=SESSION#<id>,  sk=VERDICT                moderator synthesis
  pk=SESSION#<id>,  sk=EVAL                   eval metrics for the session
  pk=SESSION#<id>,  sk=FEEDBACK               user thumbs rating
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Any

import boto3

from backend.conductor.personas import Persona, PersonaConfig
from backend.shared import config as cfg


@lru_cache(maxsize=1)
def _table():
    return boto3.resource("dynamodb", region_name=cfg.REGION).Table(cfg.TABLE_NAME)


def _now() -> int:
    return int(time.time())


# ---------- Sessions ----------

def create_session(
    session_id: str,
    input_audio_key: str,
    lang: str | None = None,
) -> None:
    _table().put_item(
        Item={
            "pk": f"SESSION#{session_id}",
            "sk": "META",
            "session_id": session_id,
            "status": "ingest",
            "input_audio_s3_key": input_audio_key,
            "language": lang or "",
            "dilemma_text": "",
            "created_at": _now(),
        }
    )


def update_session(session_id: str, **attrs: Any) -> None:
    """Partial update of the META item."""
    if not attrs:
        return
    names = {f"#{k}": k for k in attrs}
    values = {f":{k}": v for k, v in attrs.items()}
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in attrs)
    _table().update_item(
        Key={"pk": f"SESSION#{session_id}", "sk": "META"},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


def append_line(
    session_id: str,
    index: int,
    role: str,
    text: str,
    audio_s3_key: str | None = None,
) -> None:
    _table().put_item(
        Item={
            "pk": f"SESSION#{session_id}",
            "sk": f"LINE#{index:03d}#{role}",
            "index": index,
            "role": role,
            "text": text,
            "audio_s3_key": audio_s3_key or "",
            "timestamp": _now(),
        }
    )


def set_verdict(session_id: str, text: str, audio_s3_key: str | None = None) -> None:
    _table().put_item(
        Item={
            "pk": f"SESSION#{session_id}",
            "sk": "VERDICT",
            "text": text,
            "audio_s3_key": audio_s3_key or "",
            "timestamp": _now(),
        }
    )


def write_eval(
    session_id: str,
    coverage_pct: float,
    voice_scores: dict[str, int],
    diversity_score: float,
    baseline_considerations: list[str],
    judge_reasoning: str,
) -> None:
    _table().put_item(
        Item={
            "pk": f"SESSION#{session_id}",
            "sk": "EVAL",
            "coverage_pct": str(coverage_pct),
            "voice_scores": {k: str(v) for k, v in voice_scores.items()},
            "diversity_score": str(diversity_score),
            "baseline_considerations": baseline_considerations,
            "judge_reasoning": judge_reasoning,
            "timestamp": _now(),
        }
    )


def read_session(session_id: str) -> dict[str, Any]:
    """Read all items for a session under one pk partition."""
    resp = _table().query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(f"SESSION#{session_id}")
    )
    return {"items": resp.get("Items", [])}


# ---------- Personas (loaded from DDB at Lambda cold start) ----------

def load_personas_from_ddb() -> PersonaConfig:
    resp = _table().query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq("PERSONA")
    )
    items = resp.get("Items", [])
    if not items:
        raise RuntimeError(
            "No PERSONA items found in DynamoDB. Run `python -m scripts.bootstrap_personas` first."
        )

    personas: dict[str, Persona] = {}
    reactivity: dict[str, dict[str, float]] = {}
    for it in items:
        key = it["sk"]
        personas[key] = Persona(
            key=key,
            name=it["name"],
            display_name=it["display_name"],
            definition=it["definition"],
            signature_phrases_es=list(it.get("signature_phrases_es", [])),
            signature_phrases_en=list(it.get("signature_phrases_en", [])),
            polly_voice_es=it["polly_voice_es"],
            polly_voice_en=it["polly_voice_en"],
        )
        reactivity[key] = {k: float(v) for k, v in it.get("reactivity_weights", {}).items()}

    order = ["abuela", "mama", "tio", "prima", "primo"]
    order = [k for k in order if k in personas]
    return PersonaConfig(
        order=order,
        lines_per_round=[5, 4, 3],
        personas=personas,
        reactivity=reactivity,
    )
