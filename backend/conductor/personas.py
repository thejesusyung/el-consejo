"""Persona loading and family-rhythm turn picker.

The turn order is deterministic app code, not LLM-routed:
  Round 1: fixed order from personas.json (matriarchal opening).
  Rounds 2+: weighted random sampling using the reactivity matrix, where
  weights[last_speaker][next] encodes how likely each persona is to follow
  the last one (e.g. after Tío is cynical, Mamá is more likely to respond).

Self-following is heavily discouraged via low diagonal weights.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

PERSONAS_PATH = Path(__file__).resolve().parents[2] / "personas.json"


@dataclass
class Persona:
    key: str
    name: str
    display_name: str
    definition: str
    signature_phrases_es: list[str]
    signature_phrases_en: list[str]
    polly_voice_es: str
    polly_voice_en: str
    tts_voice_description: str = ""

    def signature_for(self, lang: str) -> list[str]:
        return self.signature_phrases_es if lang.startswith("es") else self.signature_phrases_en

    def polly_voice_for(self, lang: str) -> str:
        return self.polly_voice_es if lang.startswith("es") else self.polly_voice_en

    def tts_voice_prompt(self) -> str:
        """Voice style string passed to OpenRouter TTS as the voice parameter."""
        return f"{self.tts_voice_description} speaking to a family member"


@dataclass
class PersonaConfig:
    order: list[str]
    lines_per_round: list[int]
    personas: dict[str, Persona]
    reactivity: dict[str, dict[str, float]]


def load_config(path: Path | None = None) -> PersonaConfig:
    data = json.loads((path or PERSONAS_PATH).read_text())
    personas = {k: Persona(key=k, **v) for k, v in data["personas"].items()}
    return PersonaConfig(
        order=data["order"],
        lines_per_round=data["lines_per_round"],
        personas=personas,
        reactivity=data["reactivity"],
    )


def plan_turns(cfg: PersonaConfig, rng: random.Random | None = None) -> list[str]:
    """Return a flat list of persona keys in speaking order across all rounds."""
    rng = rng or random.Random()
    turns: list[str] = []

    for round_idx, count in enumerate(cfg.lines_per_round):
        if round_idx == 0:
            turns.extend(cfg.order[:count])
            continue

        last = turns[-1]
        for _ in range(count):
            weights_map = cfg.reactivity[last]
            keys = list(weights_map.keys())
            weights = [weights_map[k] for k in keys]
            pick = rng.choices(keys, weights=weights, k=1)[0]
            turns.append(pick)
            last = pick

    return turns
