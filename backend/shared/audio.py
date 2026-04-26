"""Transcribe (voice note → text + language) and Polly (persona line → MP3).

Transcribe is used once per session with automatic language identification
(Spanish vs English). Polly is used once per persona line to synthesize the
panel's spoken audio to S3.
"""
from __future__ import annotations

import json
import time
import uuid
from functools import lru_cache

import boto3

from backend.shared import config as cfg


SUPPORTED_LANGS = ["es-US", "en-US"]


@lru_cache(maxsize=1)
def _transcribe():
    return boto3.client("transcribe", region_name=cfg.REGION)


@lru_cache(maxsize=1)
def _polly():
    return boto3.client("polly", region_name=cfg.REGION)


@lru_cache(maxsize=1)
def _s3():
    return boto3.client("s3", region_name=cfg.REGION)


# ---------- Transcribe ----------

def transcribe(
    input_bucket: str,
    input_key: str,
    output_bucket: str,
    poll_interval: float = 2.0,
    timeout: float = 180.0,
) -> tuple[str, str]:
    """Kick off a Transcribe job, wait for it, return (text, language_code).

    The audio file's media format is inferred from the key's extension.
    """
    job_name = f"elconsejo-{uuid.uuid4().hex[:12]}"
    media_fmt = input_key.rsplit(".", 1)[-1].lower()
    if media_fmt not in {"mp3", "mp4", "wav", "flac", "ogg", "amr", "webm", "m4a"}:
        media_fmt = "mp3"

    output_key = f"transcripts/{job_name}.json"

    _transcribe().start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": f"s3://{input_bucket}/{input_key}"},
        MediaFormat=media_fmt,
        IdentifyLanguage=True,
        LanguageOptions=SUPPORTED_LANGS,
        OutputBucketName=output_bucket,
        OutputKey=output_key,
    )

    deadline = time.time() + timeout
    while True:
        r = _transcribe().get_transcription_job(TranscriptionJobName=job_name)
        status = r["TranscriptionJob"]["TranscriptionJobStatus"]
        if status == "COMPLETED":
            break
        if status == "FAILED":
            reason = r["TranscriptionJob"].get("FailureReason", "unknown")
            raise RuntimeError(f"Transcribe failed: {reason}")
        if time.time() > deadline:
            raise TimeoutError(f"Transcribe job {job_name} did not complete in {timeout}s")
        time.sleep(poll_interval)

    # Fetch + parse the output JSON from S3.
    obj = _s3().get_object(Bucket=output_bucket, Key=output_key)
    data = json.loads(obj["Body"].read())
    text = data["results"]["transcripts"][0]["transcript"]
    lang_full = r["TranscriptionJob"].get("LanguageCode", "es-US")
    lang = "es" if lang_full.startswith("es") else "en"
    return text.strip(), lang


# ---------- Polly ----------

def synthesize_to_s3(
    text: str,
    voice_id: str,
    bucket: str,
    key: str,
    lang_code: str = "es-US",
) -> None:
    """Synthesize `text` with Polly neural voice, upload MP3 to s3://bucket/key."""
    resp = _polly().synthesize_speech(
        Text=text,
        VoiceId=voice_id,
        OutputFormat="mp3",
        Engine="neural",
        LanguageCode=lang_code,
    )
    audio = resp["AudioStream"].read()
    _s3().put_object(Bucket=bucket, Key=key, Body=audio, ContentType="audio/mpeg")


def polly_lang_code(lang: str) -> str:
    return "es-US" if lang.startswith("es") else "en-US"
