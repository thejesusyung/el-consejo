"""Phase 1 — one-time bootstrap.

Idempotent: safe to re-run. It will:
  1. Create the S3 assets bucket if missing.
  2. Create the DynamoDB table if missing (on-demand billing).
  3. For each persona in personas.json:
       - Generate a portrait via Bedrock Nova Canvas (skipped if already in S3).
       - Upload the portrait PNG to s3://<assets>/portraits/<key>.png.
       - Upsert the persona item into DynamoDB.

Usage:
    python -m scripts.bootstrap_personas              # generate missing + seed
    python -m scripts.bootstrap_personas --force      # regenerate all portraits
    python -m scripts.bootstrap_personas --dry-run    # print what would happen
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from backend.shared import config as cfg
from backend.conductor.personas import load_config


PORTRAIT_STYLE = (
    "warm digital illustration, soft painted style, cohesive family portrait "
    "set, gentle natural lighting, clean simple background, friendly expression"
)

NEGATIVE_PROMPT = (
    "text, words, letters, watermark, signature, logo, multiple people, crowd, "
    "deformed hands, extra fingers, extra limbs, distorted face, blurry, "
    "low quality, nsfw"
)

PORTRAIT_PROMPTS = {
    "abuela": (
        "Warm portrait of an elderly Latin American grandmother, around 75 years "
        "old, silver hair pulled into a loose bun, floral apron over a soft "
        "blouse, warm kind eyes with laugh lines, gentle small smile, sunlit "
        "home kitchen background softly blurred, " + PORTRAIT_STYLE
    ),
    "mama": (
        "Warm portrait of a Latin American mother, around 50 years old, long "
        "dark hair with a few soft grays, cozy cardigan, caring attentive eyes, "
        "gentle warm smile, softly lit home interior background, " + PORTRAIT_STYLE
    ),
    "tio": (
        "Warm portrait of a Latin American uncle, around 55 years old, short "
        "graying hair, salt-and-pepper mustache, casual short-sleeve button-up "
        "shirt, one eyebrow slightly raised in skepticism, relaxed amused "
        "expression, sunny patio background softly blurred, " + PORTRAIT_STYLE
    ),
    "prima": (
        "Warm portrait of a Latin American woman in her late 20s, wavy shoulder-"
        "length dark hair, minimal modern earrings, stylish clean-lined neutral "
        "top, confident thoughtful expression, subtle smile, modern apartment "
        "background softly blurred, " + PORTRAIT_STYLE
    ),
    "primo": (
        "Warm portrait of a Latin American man in his late 20s, short dark hair, "
        "a small trimmed beard, casual t-shirt under an open short-sleeve shirt, "
        "playful crooked smile, laid-back posture, sunny outdoor patio softly "
        "blurred, " + PORTRAIT_STYLE
    ),
}


def _ensure_bucket(s3, name: str, region: str, dry: bool) -> None:
    try:
        s3.head_bucket(Bucket=name)
        print(f"  ✓ bucket {name} exists")
        return
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code not in ("404", "NoSuchBucket", "NotFound"):
            # 403 can mean exists-but-not-ours; surface it.
            raise
    if dry:
        print(f"  [dry-run] would create bucket {name}")
        return
    print(f"  … creating bucket {name}")
    if region == "us-east-1":
        s3.create_bucket(Bucket=name)
    else:
        s3.create_bucket(
            Bucket=name,
            CreateBucketConfiguration={"LocationConstraint": region},
        )
    print(f"  ✓ bucket {name} created")


def _ensure_table(ddb, name: str, dry: bool) -> None:
    try:
        ddb.describe_table(TableName=name)
        print(f"  ✓ table {name} exists")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    if dry:
        print(f"  [dry-run] would create table {name}")
        return
    print(f"  … creating table {name}")
    ddb.create_table(
        TableName=name,
        BillingMode="PAY_PER_REQUEST",
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
    )
    print(f"  … waiting for {name} to become ACTIVE")
    ddb.get_waiter("table_exists").wait(TableName=name)
    print(f"  ✓ table {name} created")


def _portrait_exists(s3, bucket: str, key: str) -> bool:
    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def _generate_portrait(bedrock, prompt: str) -> bytes:
    body = {
        "taskType": "TEXT_IMAGE",
        "textToImageParams": {"text": prompt, "negativeText": NEGATIVE_PROMPT},
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "quality": "standard",
            "height": 1024,
            "width": 1024,
            "cfgScale": 7.0,
        },
    }
    for attempt in range(6):
        try:
            resp = bedrock.invoke_model(modelId=cfg.NOVA_CANVAS_MODEL_ID, body=json.dumps(body))
            data = json.loads(resp["body"].read())
            return base64.b64decode(data["images"][0])
        except bedrock.exceptions.ThrottlingException:
            if attempt == 5:
                raise
            wait = 30 * (2 ** attempt) + random.uniform(0, 5)
            print(f"     throttled — waiting {wait:.0f}s before retry {attempt + 1}/5")
            time.sleep(wait)


def _upsert_persona(table, persona_key: str, persona_obj, reactivity: dict, portrait_key: str) -> None:
    item = {
        "pk": "PERSONA",
        "sk": persona_key,
        "name": persona_obj.name,
        "display_name": persona_obj.display_name,
        "definition": persona_obj.definition,
        "signature_phrases_es": persona_obj.signature_phrases_es,
        "signature_phrases_en": persona_obj.signature_phrases_en,
        "polly_voice_es": persona_obj.polly_voice_es,
        "polly_voice_en": persona_obj.polly_voice_en,
        "portrait_s3_key": portrait_key,
        "reactivity_weights": {k: str(v) for k, v in reactivity.items()},
    }
    table.put_item(Item=item)


def main() -> int:
    parser = argparse.ArgumentParser(description="El Consejo — Phase 1 bootstrap")
    parser.add_argument("--force", action="store_true", help="Regenerate portraits even if present.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without writing.")
    parser.add_argument("--skip-portraits", action="store_true", help="Seed DDB without generating portraits.")
    args = parser.parse_args()

    region = cfg.REGION
    print(f"Region: {region}")
    print(f"Table:  {cfg.TABLE_NAME}")
    print(f"Assets: {cfg.BUCKET_ASSETS}\n")

    s3 = boto3.client("s3", region_name=region)
    ddb = boto3.client("dynamodb", region_name=region)
    ddb_res = boto3.resource("dynamodb", region_name=region)
    bedrock = boto3.client("bedrock-runtime", region_name=region)

    print("▸ Infra")
    _ensure_bucket(s3, cfg.BUCKET_ASSETS, region, args.dry_run)
    _ensure_table(ddb, cfg.TABLE_NAME, args.dry_run)

    if args.dry_run:
        print("\n[dry-run] stopping before portraits + seed")
        return 0

    table = ddb_res.Table(cfg.TABLE_NAME)
    pcfg = load_config()

    print("\n▸ Personas")
    for key in pcfg.order:
        persona = pcfg.personas[key]
        s3_key = cfg.portrait_key(key)
        have_portrait = _portrait_exists(s3, cfg.BUCKET_ASSETS, s3_key)

        if args.skip_portraits:
            print(f"  ↷ {persona.display_name:<14} skipping portrait generation")
        elif have_portrait and not args.force:
            print(f"  ✓ {persona.display_name:<14} portrait already in s3://{cfg.BUCKET_ASSETS}/{s3_key}")
        else:
            print(f"  … {persona.display_name:<14} generating portrait")
            t0 = time.time()
            png = _generate_portrait(bedrock, PORTRAIT_PROMPTS[key])
            s3.put_object(
                Bucket=cfg.BUCKET_ASSETS,
                Key=s3_key,
                Body=png,
                ContentType="image/png",
            )
            print(f"     done in {time.time() - t0:.1f}s → s3://{cfg.BUCKET_ASSETS}/{s3_key}")

        _upsert_persona(table, key, persona, pcfg.reactivity[key], s3_key)
        print(f"     seeded persona item PERSONA/{key}")

    print("\n✓ bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
