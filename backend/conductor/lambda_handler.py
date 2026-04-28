"""Conductor Lambda — consumes SQS messages, runs the full pipeline.

Per message:
  1. Parse session_id + input audio key.
  2. Transcribe (detects language).
  3. Load personas from DynamoDB.
  4. run_session with an on_line callback that:
       - persists each line to DDB as it arrives (frontend can poll and see
         the conversation stream in)
       - TTS via Polly → audio-out S3 → updates the line with audio key
       - moderator_close lands as VERDICT item instead of LINE
  5. Enqueue the eval job (Phase 5 consumer).
  6. Flip session status to `done`.

Errors flip status to `failed` with an error message before re-raising so the
frontend can surface the problem instead of showing an infinite spinner.
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache

import boto3

from backend.conductor.core import Line, run_session
from backend.shared import audio, config as cfg, storage

try:
    from backend.ws.handler import broadcast as ws_broadcast
except Exception:  # WS module absent in older bundles — graceful degrade.
    def ws_broadcast(session_id: str, message: dict, endpoint: str | None = None) -> None:
        return None

log = logging.getLogger()
log.setLevel(logging.INFO)


@lru_cache(maxsize=1)
def _sqs():
    return boto3.client("sqs", region_name=cfg.REGION)


_MODERATOR_TTS_DESCRIPTION = (
    "Warm, calm bilingual moderator with a Latin accent, measured and clear pace"
    " speaking to a family member"
)


def _synthesize(text: str, voice_description: str, bucket: str, key: str, lang: str) -> None:
    """Dispatch TTS to OpenRouter or Polly depending on TTS_BACKEND env var."""
    if cfg.TTS_BACKEND == "openrouter":
        audio.synthesize_with_openrouter(
            text=text,
            voice_description=voice_description,
            bucket=bucket,
            key=key,
        )
    else:
        audio.synthesize_to_s3(
            text=text,
            voice_id=voice_description,  # polly path: description IS the voice_id
            bucket=bucket,
            key=key,
            lang_code=audio.polly_lang_code(lang),
        )


def _build_line_callback(session_id: str, lang: str, personas):
    """Returns an on_line callback that persists each line + its TTS audio."""

    def on_line(line: Line, idx: int) -> None:
        if line.role == "moderator_close":
            audio_key = f"sessions/{session_id}/verdict.mp3"
            verdict_voice = (
                _MODERATOR_TTS_DESCRIPTION if cfg.TTS_BACKEND == "openrouter"
                else _moderator_polly_voice(lang)
            )
            try:
                _synthesize(line.text, verdict_voice, cfg.BUCKET_AUDIO_OUT, audio_key, lang)
            except Exception:
                log.exception("tts failed for verdict")
                audio_key = ""
            storage.set_verdict(session_id, line.text, audio_s3_key=audio_key)
            ws_broadcast(session_id, {
                "type": "verdict",
                "text": line.text,
                "audio_s3_key": audio_key,
            })
            return

        if line.role == "moderator_open":
            voice = (
                _MODERATOR_TTS_DESCRIPTION if cfg.TTS_BACKEND == "openrouter"
                else _moderator_polly_voice(lang)
            )
        elif cfg.TTS_BACKEND == "openrouter":
            voice = personas.personas[line.role].tts_voice_prompt()
        else:
            voice = personas.personas[line.role].polly_voice_for(lang)

        audio_key = f"sessions/{session_id}/line_{idx:03d}.mp3"
        try:
            _synthesize(line.text, voice, cfg.BUCKET_AUDIO_OUT, audio_key, lang)
        except Exception:
            log.exception("tts failed for line %s", idx)
            audio_key = ""
        storage.append_line(
            session_id=session_id,
            index=idx,
            role=line.role,
            text=line.text,
            audio_s3_key=audio_key,
        )
        ws_broadcast(session_id, {
            "type": "line",
            "index": idx,
            "role": line.role,
            "text": line.text,
            "audio_s3_key": audio_key,
        })

    return on_line


def _moderator_polly_voice(lang: str) -> str:
    return "Pedro" if lang == "es" else "Stephen"


def _run_panel(session_id: str, dilemma: str, lang: str) -> None:
    try:
        storage.update_session(session_id, status="running", language=lang, dilemma_text=dilemma)
        ws_broadcast(session_id, {
            "type": "status", "status": "running", "language": lang, "dilemma": dilemma,
        })
        personas = storage.load_personas_from_ddb()
        on_line = _build_line_callback(session_id, lang, personas)
        run_session(dilemma=dilemma, lang=lang, cfg=personas, on_line=on_line)

        eval_url = os.environ.get("ELCONSEJO_SQS_EVAL_URL", cfg.SQS_EVAL_URL)
        if eval_url:
            _sqs().send_message(
                QueueUrl=eval_url,
                MessageBody=json.dumps({"session_id": session_id}),
            )
        storage.update_session(session_id, status="done")
        ws_broadcast(session_id, {"type": "status", "status": "done"})
        log.info("done session=%s", session_id)
    except Exception as e:
        log.exception("session failed %s", session_id)
        storage.update_session(session_id, status="failed", error=str(e)[:500])
        ws_broadcast(session_id, {"type": "status", "status": "failed", "error": str(e)[:500]})
        raise


def _process_message(body: dict) -> None:
    session_id = body["session_id"]

    # Text-input path: dilemma already transcribed by the caller.
    if body.get("dilemma_text"):
        dilemma = body["dilemma_text"].strip()
        lang = body.get("language", "es")
        log.info("text session=%s lang=%s chars=%d", session_id, lang, len(dilemma))
        _run_panel(session_id, dilemma, lang)
        return

    bucket = body["bucket"]
    key = body["key"]
    log.info("audio session=%s key=%s", session_id, key)

    try:
        storage.update_session(session_id, status="transcribing")
        ws_broadcast(session_id, {"type": "status", "status": "transcribing"})
        dilemma, lang = audio.transcribe(
            input_bucket=bucket,
            input_key=key,
            output_bucket=cfg.BUCKET_TRANSCRIPTS,
        )
        log.info("transcribed session=%s lang=%s chars=%d", session_id, lang, len(dilemma))
        _run_panel(session_id, dilemma, lang)
    except Exception as e:
        log.exception("session failed %s", session_id)
        storage.update_session(session_id, status="failed", error=str(e)[:500])
        ws_broadcast(session_id, {"type": "status", "status": "failed", "error": str(e)[:500]})
        raise


def handler(event: dict, _context) -> dict:
    processed = 0
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        _process_message(body)
        processed += 1
    return {"processed": processed}
