# El Consejo

AWS-native Latin family AI advice panel. Record a voice note describing a life
dilemma → five hand-authored AI personas (Abuela, Mamá, Tío, Prima, Primo)
argue about it across three rounds while a moderator synthesizes a verdict.
Streams live to the browser with per-line TTS audio and a parallel LLM-as-judge
eval pipeline (coverage / voice consistency / diversity).

Plan file: `~/.claude/plans/dreamy-rolling-rose.md`.

## Architecture

```
Browser (React, S3 + CloudFront)
   │ record voice note
   ▼
API Gateway (HTTP + WebSocket) ──► Lambda: api, ws
   │ presigned URL / live transcript push
   ▼
S3 audio-in ─► Lambda: ingest ─► SQS ─► Lambda: conductor
                                           │
                                           ├─► Amazon Transcribe  (voice → text + language)
                                           ├─► Bedrock Runtime (Converse API)
                                           │     Haiku   × panelists (5 × 3 rounds)
                                           │     Sonnet  × moderator open/close
                                           ├─► Polly (TTS per line → S3 audio-out)
                                           ├─► DynamoDB (session state + WS broadcast)
                                           └─► SQS eval ─► Lambda: eval_worker
                                                             ├─► Bedrock Sonnet baseline
                                                             ├─► Bedrock Haiku judge
                                                             ├─► Titan Embed (diversity)
                                                             └─► CloudWatch metrics
```

## Repo layout

```
backend/
  conductor/       panel orchestration (core + CLI + Lambda) + eval rubric
  ingest/          S3-triggered Lambda — enqueues conductor jobs
  api/             HTTP API Lambda — /presign, /sessions/:id, /feedback/:id
  ws/              WebSocket Lambda — $connect, $disconnect, watch
  eval_worker/     SQS-triggered eval Lambda
  shared/          config, DynamoDB storage helpers, audio (Transcribe + Polly)
scripts/
  bootstrap_personas.py   one-time: creates assets bucket + DDB table, generates 5 portraits via Nova Canvas, seeds persona items
  build_lambdas.py        assembles build/<name>/ asset dirs that CDK references
infra/
  elconsejo_stack.py      full CDK stack (buckets, table, queues, Lambdas, API GW, CloudFront)
frontend/
  Vite + React + TypeScript single-page app
personas.json             source of truth for persona definitions + 5x5 reactivity matrix
```

## Prerequisites

- AWS account + credentials (`aws configure`).
- Bedrock model access enabled in `us-east-1`:
  - `anthropic.claude-haiku-4-5-20251001-v1:0`
  - `anthropic.claude-sonnet-4-5-20250929-v1:0`
  - `amazon.nova-canvas-v1:0`
  - `amazon.titan-embed-text-v2:0`
- Node.js ≥ 20 (for frontend + CDK).
- AWS CDK v2 CLI: `npm install -g aws-cdk`.
- Python ≥ 3.12.

## Phase 0 — local prototype (no infra)

```bash
make install
python3 -m backend.conductor.handler --dilemma "Mi novio no quiere conocer a mi familia"
```

Validates persona voices, moderator framing, and eval rubric before any
infrastructure spend. Costs ~$0.015 per run.

## Deploy

```bash
# 1. one-time: bootstrap CDK in this account/region
cd infra && cdk bootstrap && cd ..

# 2. build Lambda bundles + deploy stack (buckets, DDB, queues, Lambdas, APIs, CDN)
make deploy

# 3. seed personas (generates portraits, writes items). Re-runs are idempotent.
make bootstrap

# 4. build + upload frontend
#    Fill these from `make deploy` outputs first:
cat > frontend/.env.production <<EOF
VITE_API_URL=https://<api-id>.execute-api.us-east-1.amazonaws.com
VITE_WS_URL=wss://<ws-id>.execute-api.us-east-1.amazonaws.com/prod
VITE_ASSETS_URL=https://elconsejo-assets-<account>.s3.amazonaws.com
VITE_AUDIO_OUT_URL=https://elconsejo-audio-out-<account>.s3.amazonaws.com
EOF
make frontend-build
aws s3 sync frontend/dist s3://<FrontendBucket>/
```

Visit the CloudFront URL printed as `CdnUrl` in the CDK outputs.

## Cost

Free-tier-friendly for everything except Bedrock (no free tier):

| Item | Per session |
|---|---|
| Bedrock Haiku (panelists + judge) | ~$0.003 |
| Bedrock Sonnet (moderator + baseline) | ~$0.010 |
| Titan embeddings | < $0.001 |
| Transcribe | free ≤ 60 min/mo then $0.024/min |
| Polly | free ≤ 5M chars/mo |
| Everything else | $0 at demo volume |

**~$0.013 per completed session.** One-time Nova Canvas portrait generation: ~$0.20.

## Eval dimensions

Per session the eval Lambda writes one EVAL item and three CloudWatch metrics:

- **Coverage** — of N considerations a frontier model would raise, how many did
  the panel collectively surface? Target ≥ 75%.
- **Voice consistency** (per persona) — judged 1-5 against each persona's
  definition.
- **Diversity** — `1 - mean(pairwise cosine similarity)` over persona
  embeddings. Higher = personas actually disagreed.

Coverage uses Claude Sonnet to produce the reference considerations; a Claude
Haiku judge does the scoring.

## Tearing down

```bash
cd infra && cdk destroy
```

The Assets bucket + DynamoDB table have RETAIN removal policies — delete them
by hand after destroy if you want a full reset.
