"""Eval pipeline: coverage + voice consistency + diversity.

Framing (see plan): the parallel frontier-model output is NOT ground truth, it
is a coverage check. We want the panel to produce diverse, opinionated output
while still surfacing the key considerations a single frontier call would raise.

Metrics:
  coverage_pct     — share of baseline "key considerations" that were addressed
                     somewhere in the panel transcript (judge LLM, 0-100)
  voice_scores     — per-persona fidelity to their definition (judge LLM, 1-5)
  diversity_score  — 1 - mean pairwise cosine similarity of persona embeddings
                     (higher = personas actually disagreed / didn't echo)
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from . import llm as bc
from .personas import PersonaConfig


@dataclass
class EvalResult:
    coverage_pct: float
    baseline_considerations: list[str]
    voice_scores: dict[str, int] = field(default_factory=dict)
    diversity_score: float = 0.0
    judge_reasoning: str = ""


BASELINE_SYS = (
    "You are a thoughtful advisor. Given a personal dilemma, list the key "
    "considerations that a responsible panel should address. Be specific and "
    "exhaustive. Return a JSON array of short strings, 4-8 items."
)

COVERAGE_SYS = (
    "You are an evaluator. You will be given a list of KEY CONSIDERATIONS and "
    "a PANEL TRANSCRIPT. For each consideration, decide if the panel "
    "collectively addressed it (even indirectly, by any persona). Return ONLY "
    "a JSON object: {\"addressed\": [bool, bool, ...], \"reasoning\": \"...\"} "
    "with one bool per consideration in order."
)

VOICE_SYS = (
    "You are an evaluator of persona fidelity. Given a PERSONA DEFINITION and "
    "a persona's LINES from a conversation, rate on 1-5 how well the lines "
    "match the persona's voice, values, and characteristic expressions. "
    "Return ONLY a JSON object: {\"score\": 1-5, \"reasoning\": \"...\"}."
)


def _parse_json(text: str) -> object:
    match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
    return json.loads(match.group(0) if match else text)


def baseline_considerations(dilemma: str) -> list[str]:
    raw = bc.sonnet(BASELINE_SYS, f"Dilemma:\n{dilemma}", temperature=0.3, max_tokens=500)
    data = _parse_json(raw)
    return [str(x) for x in data]  # type: ignore[arg-type]


def score_coverage(considerations: list[str], transcript: str) -> tuple[float, str]:
    prompt = (
        f"KEY CONSIDERATIONS:\n{json.dumps(considerations, ensure_ascii=False)}\n\n"
        f"PANEL TRANSCRIPT:\n{transcript}"
    )
    raw = bc.haiku(COVERAGE_SYS, prompt, temperature=0.0, max_tokens=600)
    data = _parse_json(raw)
    addressed = data["addressed"]  # type: ignore[index]
    pct = 100.0 * sum(1 for b in addressed if b) / max(len(addressed), 1)
    return pct, data.get("reasoning", "")  # type: ignore[union-attr]


def score_voice(persona_key: str, cfg: PersonaConfig, lines: list[str]) -> int:
    if not lines:
        return 0
    persona = cfg.personas[persona_key]
    prompt = (
        f"PERSONA DEFINITION ({persona.display_name}):\n{persona.definition}\n\n"
        f"LINES:\n" + "\n".join(f"- {ln}" for ln in lines)
    )
    raw = bc.haiku(VOICE_SYS, prompt, temperature=0.0, max_tokens=300)
    return int(_parse_json(raw)["score"])  # type: ignore[index]


def _cos(a: list[float], b: list[float]) -> float:
    # Titan embeddings are already normalized when requested; dot product = cosine.
    return sum(x * y for x, y in zip(a, b))


def score_diversity(persona_texts: dict[str, str]) -> float:
    keys = [k for k, v in persona_texts.items() if v]
    if len(keys) < 2:
        return 0.0
    try:
        embs = [bc.embed(persona_texts[k]) for k in keys]
    except NotImplementedError:
        return -1.0
    pairs = [(i, j) for i in range(len(keys)) for j in range(i + 1, len(keys))]
    mean_sim = sum(_cos(embs[i], embs[j]) for i, j in pairs) / len(pairs)
    return round(1.0 - mean_sim, 3)


def run_eval(
    dilemma: str,
    transcript: str,
    per_persona_lines: dict[str, list[str]],
    cfg: PersonaConfig,
) -> EvalResult:
    considerations = baseline_considerations(dilemma)
    coverage_pct, reasoning = score_coverage(considerations, transcript)
    voice_scores = {k: score_voice(k, cfg, lines) for k, lines in per_persona_lines.items()}
    persona_texts = {k: " ".join(lines) for k, lines in per_persona_lines.items() if lines}
    diversity = score_diversity(persona_texts)
    return EvalResult(
        coverage_pct=round(coverage_pct, 1),
        baseline_considerations=considerations,
        voice_scores=voice_scores,
        diversity_score=diversity,
        judge_reasoning=reasoning,
    )
