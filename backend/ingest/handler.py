"""Ingest Lambda — triggered by S3 ObjectCreated on the audio-in bucket.

Convention: the client uploads to `sessions/<session_id>.<ext>` using a
presigned URL that already embeds the session ID. We parse the key, create
a SESSION#<id> META item in DynamoDB, and enqueue a conductor job on SQS.
"""
from __future__ import annotations

import json
import os
import uuid
from functools import lru_cache
from urllib.parse import unquote_plus

import boto3

from backend.shared import config as cfg
from backend.shared import storage


@lru_cache(maxsize=1)
def _sqs():
    return boto3.client("sqs", region_name=cfg.REGION)


def _session_id_from_key(key: str) -> str:
    base = key.rsplit("/", 1)[-1]
    sid = base.rsplit(".", 1)[0]
    # If the client didn't generate a valid-looking ID, mint one.
    if len(sid) < 8:
        sid = uuid.uuid4().hex
    return sid


def handler(event: dict, _context) -> dict:
    queue_url = os.environ.get("ELCONSEJO_SQS_CONDUCTOR_URL", cfg.SQS_CONDUCTOR_URL)
    if not queue_url:
        raise RuntimeError("ELCONSEJO_SQS_CONDUCTOR_URL is not set for this Lambda")

    enqueued = 0
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])
        session_id = _session_id_from_key(key)

        storage.create_session(session_id=session_id, input_audio_key=key)

        _sqs().send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({
                "session_id": session_id,
                "bucket": bucket,
                "key": key,
            }),
        )
        enqueued += 1

    return {"enqueued": enqueued}
