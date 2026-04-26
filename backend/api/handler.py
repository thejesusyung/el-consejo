"""HTTP API Lambda — routes to simple endpoints via HTTP API's
$request.path parsing.

Endpoints:
  POST /presign           body {ext?:"webm"} → {session_id, put_url}
  GET  /sessions/{id}     → full session state (lines, verdict, eval)
  POST /feedback/{id}     body {rating:"up"|"down", comment?:""}
"""
from __future__ import annotations

import json
import time
import uuid
from functools import lru_cache
from typing import Any

import boto3

from backend.shared import config as cfg
from backend.shared import storage


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3", region_name=cfg.REGION)


def _ok(body: Any, status: int = 200) -> dict:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, ensure_ascii=False, default=str),
    }


def _err(msg: str, status: int = 400) -> dict:
    return _ok({"error": msg}, status=status)


def _presign(body: dict) -> dict:
    ext = body.get("ext", "webm").lstrip(".")
    if ext not in {"webm", "mp3", "wav", "m4a", "ogg"}:
        return _err(f"unsupported ext {ext}")

    session_id = uuid.uuid4().hex[:20]
    key = f"sessions/{session_id}.{ext}"
    content_type = {
        "webm": "audio/webm", "mp3": "audio/mpeg", "wav": "audio/wav",
        "m4a": "audio/mp4", "ogg": "audio/ogg",
    }[ext]
    put_url = _s3().generate_presigned_url(
        "put_object",
        Params={
            "Bucket": cfg.BUCKET_AUDIO_IN,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=300,
    )
    return _ok({
        "session_id": session_id,
        "put_url": put_url,
        "content_type": content_type,
    })


def _get_session(session_id: str) -> dict:
    data = storage.read_session(session_id)
    items = data["items"]
    if not items:
        return _err("session not found", status=404)

    meta = next((i for i in items if i["sk"] == "META"), {})
    verdict = next((i for i in items if i["sk"] == "VERDICT"), None)
    ev = next((i for i in items if i["sk"] == "EVAL"), None)
    lines = sorted(
        [i for i in items if i["sk"].startswith("LINE#")],
        key=lambda i: int(i.get("index", 0)),
    )
    return _ok({
        "session_id": session_id,
        "meta": meta,
        "lines": lines,
        "verdict": verdict,
        "eval": ev,
    })


def _feedback(session_id: str, body: dict) -> dict:
    rating = body.get("rating")
    if rating not in ("up", "down"):
        return _err("rating must be 'up' or 'down'")
    storage._table().put_item(Item={  # noqa: SLF001
        "pk": f"SESSION#{session_id}",
        "sk": "FEEDBACK",
        "rating": rating,
        "comment": body.get("comment", ""),
        "created_at": int(time.time()),
    })
    return _ok({"ok": True})


def _text_session(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    if not text:
        return _err("text is required")
    lang = body.get("lang", "es")
    if lang not in ("es", "en"):
        lang = "es"

    session_id = uuid.uuid4().hex[:20]
    storage.create_session(session_id=session_id, input_audio_key="", lang=lang)
    storage.update_session(session_id, dilemma_text=text, language=lang, status="queued")

    queue_url = cfg.SQS_CONDUCTOR_URL
    import boto3 as _boto3
    _boto3.client("sqs", region_name=cfg.REGION).send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({
            "session_id": session_id,
            "dilemma_text": text,
            "language": lang,
        }),
    )
    return _ok({"session_id": session_id})


def handler(event: dict, _context) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "")

    if method == "OPTIONS":
        return _ok({"ok": True})

    body: dict = {}
    if event.get("body"):
        try:
            body = json.loads(event["body"])
        except Exception:
            return _err("invalid json body")

    if path == "/presign" and method == "POST":
        return _presign(body)

    if path == "/sessions" and method == "POST":
        return _text_session(body)

    if path.startswith("/sessions/") and method == "GET":
        return _get_session(path.rsplit("/", 1)[-1])

    if path.startswith("/feedback/") and method == "POST":
        return _feedback(path.rsplit("/", 1)[-1], body)

    return _err(f"no route for {method} {path}", status=404)
