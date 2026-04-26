"""Phase 0 CLI: thin wrapper over core.run_session for local iteration.

Prints each line as it arrives, optionally runs eval, optionally dumps to JSON.

Usage:
    python -m backend.conductor.handler --dilemma "Mi novio no quiere conocer a mi familia"
    python -m backend.conductor.handler --dilemma "My sister borrowed ..." --lang en
    python -m backend.conductor.handler --dilemma-file my_dilemma.txt --json-out out/s.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import eval as ev
from .core import Line, run_session
from .personas import PersonaConfig, load_config


def _printer(cfg: PersonaConfig):
    def on_line(line: Line, _idx: int) -> None:
        if line.role.startswith("moderator"):
            tag = "veredicto" if line.role == "moderator_close" else "apertura"
            print(f"\n🎙️  Moderador ({tag}): {line.text}\n")
        else:
            print(f"  {cfg.personas[line.role].display_name}: {line.text}\n")
    return on_line


def print_eval(result: ev.EvalResult) -> None:
    print("=" * 72)
    print("  EVALUACIÓN")
    print("=" * 72)
    print(f"  Coverage:   {result.coverage_pct:.1f}%   (target ≥ 75%)")
    print(f"  Diversity:  {result.diversity_score:.3f}  (higher = personas disagreed)")
    print("  Voice consistency (1-5):")
    for persona, score in result.voice_scores.items():
        print(f"    {persona:<8} {score}")
    print("  Baseline considerations surfaced:")
    for c in result.baseline_considerations:
        print(f"    - {c}")
    if result.judge_reasoning:
        print(f"\n  Judge: {result.judge_reasoning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="El Consejo — Phase 0 CLI")
    parser.add_argument("--dilemma", type=str)
    parser.add_argument("--dilemma-file", type=Path)
    parser.add_argument("--lang", choices=["es", "en"], default="es")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--skip-eval", action="store_true")
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()

    if args.dilemma_file:
        dilemma = args.dilemma_file.read_text().strip()
    elif args.dilemma:
        dilemma = args.dilemma
    else:
        parser.error("Provide --dilemma or --dilemma-file")

    cfg = load_config()
    print(f"\n📜 Dilema ({args.lang}): {dilemma}")

    session = run_session(dilemma, args.lang, cfg, on_line=_printer(cfg), seed=args.seed)

    result: ev.EvalResult | None = None
    if not args.skip_eval:
        print("⏳ Running eval...\n")
        result = ev.run_eval(
            dilemma=dilemma,
            transcript=session.transcript(cfg),
            per_persona_lines=session.per_persona_lines(cfg),
            cfg=cfg,
        )
        print_eval(result)

    if args.json_out:
        payload = {
            "dilemma": dilemma,
            "lang": args.lang,
            "lines": [{"role": ln.role, "text": ln.text} for ln in session.lines],
            "eval": None if result is None else {
                "coverage_pct": result.coverage_pct,
                "baseline_considerations": result.baseline_considerations,
                "voice_scores": result.voice_scores,
                "diversity_score": result.diversity_score,
                "judge_reasoning": result.judge_reasoning,
            },
        }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n💾 Wrote {args.json_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
