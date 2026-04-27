"""Batch eval runner — runs all dilemmas through the panel + eval pipeline.

Outputs:
  - results/<timestamp>/sessions/*.json  — per-session detail
  - results/<timestamp>/report.json      — aggregated metrics
  - results/<timestamp>/report.md        — human-readable summary

Resume a previous run:
    python -m scripts.run_benchmark --resume results/20260426_231500

Usage:
    LLM_BACKEND=openrouter OPENROUTER_API_KEY=sk-or-... \
        python -m scripts.run_benchmark
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.conductor import eval as ev
from backend.conductor.core import run_session
from backend.conductor.personas import load_config

DILEMMAS_PATH = ROOT / "scripts" / "dilemmas.json"
RESULTS_DIR = ROOT / "results"
PAUSE_BETWEEN_SESSIONS = 5


def run_one(dilemma: dict, cfg) -> dict:
    did = dilemma["id"]
    lang = dilemma["lang"]
    text = dilemma["dilemma"]
    category = dilemma["category"]

    print(f"\n{'='*60}")
    print(f"  #{did} [{lang}] {category}")
    print(f"  {text[:80]}")
    print(f"{'='*60}")

    t0 = time.time()
    session = run_session(text, lang, cfg, seed=did)
    panel_time = time.time() - t0

    t1 = time.time()
    result = ev.run_eval(
        dilemma=text,
        transcript=session.transcript(cfg),
        per_persona_lines=session.per_persona_lines(cfg),
        cfg=cfg,
    )
    eval_time = time.time() - t1

    print(f"  Coverage: {result.coverage_pct:.1f}%  |  "
          f"Voice: {result.voice_scores}  |  "
          f"Panel: {panel_time:.1f}s  Eval: {eval_time:.1f}s")

    return {
        "id": did,
        "lang": lang,
        "category": category,
        "dilemma": text,
        "lines": [{"role": ln.role, "text": ln.text} for ln in session.lines],
        "eval": {
            "coverage_pct": result.coverage_pct,
            "baseline_considerations": result.baseline_considerations,
            "voice_scores": result.voice_scores,
            "diversity_score": result.diversity_score,
            "judge_reasoning": result.judge_reasoning,
        },
        "timing": {
            "panel_seconds": round(panel_time, 1),
            "eval_seconds": round(eval_time, 1),
        },
    }


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    coverages = [r["eval"]["coverage_pct"] for r in results]
    above_75 = sum(1 for c in coverages if c >= 75)

    all_voice = {}
    for r in results:
        for persona, score in r["eval"]["voice_scores"].items():
            all_voice.setdefault(persona, []).append(score)
    mean_voice = {k: round(sum(v) / len(v), 2) for k, v in all_voice.items()}

    by_category = {}
    for r in results:
        cat = r["category"]
        by_category.setdefault(cat, []).append(r["eval"]["coverage_pct"])
    category_means = {k: round(sum(v) / len(v), 1) for k, v in by_category.items()}

    by_lang = {}
    for r in results:
        lang = r["lang"]
        by_lang.setdefault(lang, []).append(r["eval"]["coverage_pct"])
    lang_means = {k: round(sum(v) / len(v), 1) for k, v in by_lang.items()}

    return {
        "n_sessions": n,
        "coverage_mean": round(sum(coverages) / n, 1),
        "coverage_min": min(coverages),
        "coverage_max": max(coverages),
        "coverage_above_75_pct": round(100 * above_75 / n, 1),
        "voice_consistency_mean": mean_voice,
        "voice_consistency_overall": round(
            sum(sum(v) for v in all_voice.values()) / sum(len(v) for v in all_voice.values()), 2
        ),
        "coverage_by_category": category_means,
        "coverage_by_language": lang_means,
    }


def write_report(agg: dict, out_dir: Path) -> None:
    lines = [
        "# El Consejo — Benchmark Report",
        "",
        f"**Date:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Sessions:** {agg['n_sessions']}",
        "",
        "## Coverage (panel vs. frontier model)",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Mean coverage | **{agg['coverage_mean']}%** |",
        f"| Min | {agg['coverage_min']}% |",
        f"| Max | {agg['coverage_max']}% |",
        f"| Sessions >= 75% target | **{agg['coverage_above_75_pct']}%** ({int(agg['coverage_above_75_pct'] * agg['n_sessions'] / 100)}/{agg['n_sessions']}) |",
        "",
        "## Coverage by category",
        "",
        "| Category | Mean coverage |",
        "|---|---|",
    ]
    for cat, val in sorted(agg["coverage_by_category"].items()):
        lines.append(f"| {cat} | {val}% |")

    lines += [
        "",
        "## Coverage by language",
        "",
        "| Language | Mean coverage |",
        "|---|---|",
    ]
    for lang, val in sorted(agg["coverage_by_language"].items()):
        lines.append(f"| {lang} | {val}% |")

    lines += [
        "",
        "## Voice consistency (1-5 per persona)",
        "",
        "| Persona | Mean score |",
        "|---|---|",
    ]
    for persona, score in sorted(agg["voice_consistency_mean"].items()):
        lines.append(f"| {persona} | {score} |")
    lines.append(f"| **Overall** | **{agg['voice_consistency_overall']}** |")

    lines += [
        "",
        "## Interpretation",
        "",
        "Coverage measures what fraction of key considerations a single frontier model",
        "would raise were also surfaced by the multi-persona panel of smaller models.",
        "A score of 100% means the panel collectively covered every point the frontier",
        "model identified. Voice consistency measures how well each persona stayed in",
        "character across 3 rounds of discussion.",
    ]

    (out_dir / "report.md").write_text("\n".join(lines))
    print(f"\n  Wrote {out_dir / 'report.md'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path, help="Resume a previous run directory")
    args = parser.parse_args()

    dilemmas = json.loads(DILEMMAS_PATH.read_text())
    cfg = load_config()

    if args.resume:
        out_dir = args.resume
        sessions_dir = out_dir / "sessions"
        print(f"  Resuming from {out_dir}")
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        out_dir = RESULTS_DIR / ts
        sessions_dir = out_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)

    done_ids = set()
    for f in sessions_dir.glob("*.json"):
        try:
            done_ids.add(json.loads(f.read_text())["id"])
        except (json.JSONDecodeError, KeyError):
            pass

    results = []
    for f in sorted(sessions_dir.glob("*.json")):
        try:
            results.append(json.loads(f.read_text()))
        except (json.JSONDecodeError, KeyError):
            pass

    remaining = [d for d in dilemmas if d["id"] not in done_ids]
    if done_ids:
        print(f"  {len(done_ids)} sessions already done, {len(remaining)} remaining")

    for i, d in enumerate(remaining):
        try:
            result = run_one(d, cfg)
            results.append(result)
            (sessions_dir / f"{d['id']:02d}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
        except Exception as e:
            print(f"  FAILED #{d['id']}: {type(e).__name__}: {e}")
            continue

        if i < len(remaining) - 1:
            time.sleep(PAUSE_BETWEEN_SESSIONS)

        if len(results) % 5 == 0:
            agg = aggregate(results)
            (out_dir / "report.json").write_text(json.dumps(agg, indent=2))
            write_report(agg, out_dir)
            print(f"  [checkpoint] {len(results)} sessions saved")

    if not results:
        print("No sessions completed.")
        return 1

    agg = aggregate(results)
    (out_dir / "report.json").write_text(json.dumps(agg, indent=2))
    write_report(agg, out_dir)

    print(f"\n{'='*60}")
    print(f"  BENCHMARK COMPLETE: {len(results)}/{len(dilemmas)} sessions")
    print(f"  Mean coverage: {agg['coverage_mean']}%")
    print(f"  Sessions >= 75%: {agg['coverage_above_75_pct']}%")
    print(f"  Voice consistency: {agg['voice_consistency_overall']}/5")
    print(f"  Results: {out_dir}")
    print(f"{'='*60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
