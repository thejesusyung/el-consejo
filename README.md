# El Consejo

**What if, instead of asking one smart AI for advice, you asked five opinionated
Latin family members to argue about it?**

El Consejo is a full-stack experiment that pits a panel of small AI personas
against a single frontier model to see whether a loud family dinner can match a
quiet expert. You record a voice note describing a life dilemma, and five
characters — Abuela, Mamá, Tío, Prima, and Primo — debate it across three
rounds while a moderator synthesizes the verdict. A parallel eval pipeline
measures how much ground the family actually covered.

The serious question behind the fun: **can multiple cheap, personality-driven
model calls collectively surface the same considerations as one expensive
frontier call?**

## The Experiment

We ran 37 real-life dilemmas (relationships, money, career, parenting, culture —
20 in Spanish, 17 in English) through the panel. A frontier model independently
produced 4-8 "key considerations" per dilemma. An LLM judge then scored how
many of those the family collectively addressed.

### Results

| Metric | Value |
|---|---|
| Mean coverage of frontier considerations | **61.8%** |
| Sessions that hit the 75% target | **35.1%** (13/37) |
| Best single session | **100%** |
| Voice consistency (persona fidelity, 1-5) | **4.17/5** |

### Coverage by topic

| Category | Coverage | | Category | Coverage |
|---|---|---|---|---|
| Cultural | 72.5% | | Money | 58.9% |
| Relationship | 69.6% | | Family | 57.1% |
| Parenting | 58.3% | | Career | 55.0% |

### Voice consistency per persona

| Persona | Score | Vibe check |
|---|---|---|
| Mamá | 4.95 | Never broke character. Still asking if you ate. |
| Prima | 4.62 | Therapy-speak and "literally" on point. |
| Abuela | 4.00 | Solid. Occasionally too modern for her own good. |
| Primo | 3.81 | The comic relief wavered sometimes. |
| Tío | 3.46 | Stayed blunt, but the model couldn't always hold the edge. |

### What this means

The panel covered roughly **two-thirds** of what a single frontier model would
raise — not by being smart, but by disagreeing with each other. Abuela's
traditional values catch things Prima's therapy lens misses, and Tío's bluntness
surfaces what Mamá is too polite to say. The remaining gap (~38%) is real:
smaller models miss nuanced angles like legal implications or professional
coaching. But as a first pass at exploring a problem from multiple angles, the
family dinner holds up surprisingly well.

Spanish sessions scored higher than English (66% vs 57%), which makes sense —
the personas were designed as a Latin family, so they're playing a home game in
Spanish.

The full benchmark data (per-session transcripts, scores, and judge reasoning)
lives in [`results/`](results/).

## How It Works

```
You: "Mi novio no quiere conocer a mi familia"
         │
         ▼
   ┌─ Moderator opens ─────────────────────────┐
   │                                            │
   │  Round 1:  Abuela → Mamá → Tío → Prima → Primo
   │  Round 2:  Tío → Abuela → Primo → Prima → Mamá
   │  Round 3:  Prima → Tío → Mamá → Primo → Abuela
   │                                            │
   └─ Moderator synthesizes verdict ────────────┘
         │
         ▼
   Eval: frontier model baseline → judge scores coverage
```

Each persona has a hand-written definition, signature phrases, and a 5x5
reactivity matrix (how Tío reacts to Abuela vs. how he reacts to Prima). Turn
order is shuffled each round so no one always gets the last word.

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
                                           ├─► Transcribe  (voice → text + language)
                                           ├─► LLM provider (configurable backend)
                                           │     small model  × panelists (5 × 3 rounds)
                                           │     large model  × moderator open/close
                                           ├─► Polly (TTS per line → S3 audio-out)
                                           ├─► DynamoDB (session state + WS broadcast)
                                           └─► SQS eval ─► Lambda: eval_worker
                                                             ├─► LLM baseline
                                                             ├─► LLM judge
                                                             └─► CloudWatch metrics
```

The LLM backend is swappable via a single env var (`LLM_BACKEND`). Currently
supports AWS Bedrock (Claude Haiku/Sonnet) and OpenRouter (any model, including
free-tier). The benchmark above was run entirely on free OpenRouter models
(MiniMax M2.5 for panelists, Ling-2.6-1T for moderator/eval).

## Quick Start — local (no AWS needed)

```bash
pip install -r requirements.txt

# With OpenRouter (free):
export LLM_BACKEND=openrouter
export OPENROUTER_API_KEY=sk-or-...
python3 -m backend.conductor.handler --dilemma "Mi novio no quiere conocer a mi familia"

# With AWS Bedrock:
export LLM_BACKEND=bedrock
python3 -m backend.conductor.handler --dilemma "My sister borrowed money and never paid me back" --lang en
```

## Deploy to AWS

```bash
# 1. Bootstrap CDK
cd infra && cdk bootstrap && cd ..

# 2. Build Lambda bundles + deploy
make deploy                    # defaults to Bedrock
# or with OpenRouter:
cd infra && cdk deploy -c llm_backend=openrouter -c openrouter_api_key=sk-or-...

# 3. Seed personas (generates portraits, writes items)
make bootstrap

# 4. Build + upload frontend (fill URLs from deploy outputs)
make frontend-build
aws s3 sync frontend/dist s3://<FrontendBucket>/
```

## Run the benchmark yourself

```bash
export LLM_BACKEND=openrouter
export OPENROUTER_API_KEY=sk-or-...
python3 -m scripts.run_benchmark

# Resume if interrupted:
python3 -m scripts.run_benchmark --resume results/<timestamp>
```

40 dilemmas, ~880 LLM calls. Takes 1-2 hours on free tier. Results land in
`results/<timestamp>/` with per-session JSONs and an aggregated report.

## Repo layout

```
backend/
  conductor/       panel orchestration + eval rubric + LLM provider switch
  ingest/          S3-triggered Lambda — enqueues conductor jobs
  api/             HTTP API Lambda — /presign, /sessions/:id, /feedback/:id
  ws/              WebSocket Lambda — $connect, $disconnect, watch
  eval_worker/     SQS-triggered eval Lambda
  shared/          config, DynamoDB storage, audio (Transcribe + Polly)
scripts/
  dilemmas.json           40 benchmark dilemmas across 5 categories
  run_benchmark.py        batch runner with resume support
  bootstrap_personas.py   generates portraits via Nova Canvas, seeds DDB
  build_lambdas.py        assembles Lambda deployment bundles
infra/
  elconsejo_stack.py      full CDK stack
frontend/
  Vite + React + TypeScript SPA
personas.json             persona definitions + 5x5 reactivity matrix
results/                  benchmark data (transcripts, scores, reports)
```

## Cost

Free-tier-friendly for everything except the LLM calls:

| Backend | Per session | Notes |
|---|---|---|
| OpenRouter (free models) | $0.00 | Rate-limited, occasional failures |
| AWS Bedrock (Haiku + Sonnet) | ~$0.013 | Fastest and most reliable |
| Transcribe | free ≤ 60 min/mo | |
| Polly | free ≤ 5M chars/mo | |
| Everything else (Lambda, DDB, SQS, S3) | $0 | At demo volume |
