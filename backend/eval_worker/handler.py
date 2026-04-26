"""Eval Lambda — consumes the eval SQS queue.

Per message it reads the completed session from DynamoDB, reconstructs the
transcript + per-persona line bundle, runs the three metrics (coverage,
voice, diversity), persists the EVAL item, and publishes three custom
CloudWatch metrics so the built-in console dashboard has something to plot.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache

import boto3

from backend.conductor import eval as ev
from backend.shared import config as cfg
from backend.shared import storage

log = logging.getLogger()
log.setLevel(logging.INFO)

METRIC_NAMESPACE = "ElConsejo/Eval"


@lru_cache(maxsize=1)
def _cw():
    return boto3.client("cloudwatch", region_name=cfg.REGION)


def _reconstruct(session_id: str):
    """Returns (dilemma, transcript, per_persona_lines)."""
    data = storage.read_session(session_id)
    items = data["items"]

    meta = next((i for i in items if i["sk"] == "META"), {})
    dilemma = meta.get("dilemma_text", "")
    personas = storage.load_personas_from_ddb()

    line_items = sorted(
        [i for i in items if i["sk"].startswith("LINE#")],
        key=lambda i: int(i.get("index", 0)),
    )

    def label(role: str) -> str:
        if role.startswith("moderator"):
            return "Moderador"
        return personas.personas[role].display_name

    transcript = "\n".join(f"{label(i['role'])}: {i['text']}" for i in line_items)

    per_persona: dict[str, list[str]] = {k: [] for k in personas.personas}
    for it in line_items:
        if it["role"] in per_persona:
            per_persona[it["role"]].append(it["text"])

    return dilemma, transcript, per_persona, personas


def _emit_metrics(result: ev.EvalResult) -> None:
    metrics = [
        {"MetricName": "Coverage", "Value": float(result.coverage_pct), "Unit": "Percent"},
        {"MetricName": "Diversity", "Value": float(result.diversity_score), "Unit": "None"},
    ]
    for persona, score in result.voice_scores.items():
        metrics.append({
            "MetricName": "VoiceConsistency",
            "Dimensions": [{"Name": "Persona", "Value": persona}],
            "Value": float(score),
            "Unit": "None",
        })
    _cw().put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=metrics)


def _process(session_id: str) -> None:
    log.info("evaluating session=%s", session_id)
    dilemma, transcript, per_persona, personas = _reconstruct(session_id)
    if not dilemma or not transcript:
        log.warning("session=%s missing dilemma or transcript; skipping", session_id)
        return

    result = ev.run_eval(
        dilemma=dilemma,
        transcript=transcript,
        per_persona_lines=per_persona,
        cfg=personas,
    )
    storage.write_eval(
        session_id=session_id,
        coverage_pct=result.coverage_pct,
        voice_scores=result.voice_scores,
        diversity_score=result.diversity_score,
        baseline_considerations=result.baseline_considerations,
        judge_reasoning=result.judge_reasoning,
    )
    try:
        _emit_metrics(result)
    except Exception:
        log.exception("failed to emit CloudWatch metrics for %s", session_id)
    log.info(
        "session=%s coverage=%.1f diversity=%.3f voice=%s",
        session_id, result.coverage_pct, result.diversity_score, result.voice_scores,
    )


def handler(event: dict, _context) -> dict:
    processed = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        _process(body["session_id"])
        processed += 1
    return {"processed": processed}
