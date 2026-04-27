"""Pure orchestration logic — no I/O side effects beyond Bedrock calls.

Shared by the CLI (handler.py) and the Lambda (lambda_handler.py). Each
caller supplies an `on_line` callback invoked as soon as a line is produced,
so the CLI can print, the Lambda can persist to DynamoDB, and tests can
collect to a list.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from . import llm as bc
from .personas import PersonaConfig, plan_turns


@dataclass
class Line:
    role: str  # "moderator" or persona key
    text: str


@dataclass
class Session:
    dilemma: str
    lang: str
    lines: list[Line] = field(default_factory=list)

    def transcript(self, cfg: PersonaConfig) -> str:
        def label(role: str) -> str:
            if role in ("moderator", "moderator_open", "moderator_close"):
                return "Moderador"
            return cfg.personas[role].display_name
        return "\n".join(f"{label(ln.role)}: {ln.text}" for ln in self.lines)

    def per_persona_lines(self, cfg: PersonaConfig) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {k: [] for k in cfg.personas}
        for ln in self.lines:
            if ln.role in out:
                out[ln.role].append(ln.text)
        return out


OnLine = Callable[[Line, int], None]  # (line, index) — index is position in session.lines


MODERATOR_OPEN_SYS_ES = (
    "Eres el moderador de una mesa familiar latina. Tu trabajo es abrir la "
    "conversación con una frase corta (1-2 oraciones) que presenta el problema "
    "a la familia con calidez. No des tu opinión. No resumas. Solo abre. "
    "Responde solo con tu frase, sin comillas ni etiquetas."
)
MODERATOR_OPEN_SYS_EN = (
    "You moderate a warm Latin family roundtable. Open the conversation with "
    "a short (1-2 sentence) framing that presents the problem to the family. "
    "Do not give your opinion. Do not summarize. Just open. Reply with only "
    "your line, no quotes, no labels."
)

MODERATOR_CLOSE_SYS_ES = (
    "Eres el moderador de una mesa familiar. Acabas de escuchar a la familia "
    "discutir un problema. Ahora sintetiza el veredicto colectivo en 3-4 "
    "oraciones: qué piensan, en qué coinciden, qué recomiendan. Habla con "
    "calidez pero con claridad. No repitas frases textuales de los personajes. "
    "Responde solo con tu síntesis."
)
MODERATOR_CLOSE_SYS_EN = (
    "You moderate a Latin family roundtable. You just heard the family debate "
    "a problem. Synthesize the collective verdict in 3-4 sentences: what they "
    "think, where they agree, what they recommend. Warm but clear. Don't quote "
    "personas verbatim. Reply with only the synthesis."
)

PANELIST_SYS_TEMPLATE = """You are {display_name}, a character in a warm, chaotic Latin family discussion.

YOUR CHARACTER:
{definition}

CHARACTER EXPRESSIONS (sprinkle naturally, don't force):
{signature_phrases}

RULES:
- Reply in {lang_name}, 1-3 sentences, as if speaking out loud at a family table.
- Stay fully in character. Your values, humor and verbal tics come through every line.
- React to what was said before, don't just restate your own view.
- No stage directions, no labels, no quotes around your reply. Just speak.
- Never break character to say you're an AI.
"""

LANG_NAME = {"es": "Spanish", "en": "English"}


def build_panelist_system(persona_key: str, cfg: PersonaConfig, lang: str) -> str:
    p = cfg.personas[persona_key]
    phrases = ", ".join(f'"{s}"' for s in p.signature_for(lang))
    return PANELIST_SYS_TEMPLATE.format(
        display_name=p.display_name,
        definition=p.definition,
        signature_phrases=phrases,
        lang_name=LANG_NAME.get(lang, "Spanish"),
    )


def build_panelist_user(dilemma: str, history: list[Line], cfg: PersonaConfig, lang: str) -> str:
    lead = "EL PROBLEMA" if lang == "es" else "THE PROBLEM"
    conv = "CONVERSACIÓN HASTA AHORA" if lang == "es" else "CONVERSATION SO FAR"
    now = "AHORA ES TU TURNO. Habla." if lang == "es" else "NOW IT'S YOUR TURN. Speak."
    history_str = "(nada aún)" if lang == "es" else "(nothing yet)"
    if history:
        lines = []
        for ln in history:
            who = "Moderador" if ln.role.startswith("moderator") else cfg.personas[ln.role].display_name
            lines.append(f"{who}: {ln.text}")
        history_str = "\n".join(lines)
    return f"{lead}:\n{dilemma}\n\n{conv}:\n{history_str}\n\n{now}"


def _emit(session: Session, line: Line, on_line: OnLine | None) -> None:
    session.lines.append(line)
    if on_line is not None:
        on_line(line, len(session.lines) - 1)


def run_session(
    dilemma: str,
    lang: str,
    cfg: PersonaConfig,
    *,
    on_line: OnLine | None = None,
    seed: int | None = None,
) -> Session:
    """Run a full panel: moderator open → 3 rounds of panelists → moderator close."""
    rng = random.Random(seed)
    session = Session(dilemma=dilemma, lang=lang)

    open_sys = MODERATOR_OPEN_SYS_ES if lang == "es" else MODERATOR_OPEN_SYS_EN
    opening = bc.sonnet(open_sys, dilemma, temperature=0.6, max_tokens=120)
    _emit(session, Line(role="moderator_open", text=opening), on_line)

    for persona_key in plan_turns(cfg, rng=rng):
        sys_prompt = build_panelist_system(persona_key, cfg, lang)
        user_prompt = build_panelist_user(dilemma, session.lines, cfg, lang)
        reply = bc.haiku(sys_prompt, user_prompt, temperature=0.9, max_tokens=200)
        _emit(session, Line(role=persona_key, text=reply), on_line)

    close_sys = MODERATOR_CLOSE_SYS_ES if lang == "es" else MODERATOR_CLOSE_SYS_EN
    close_user = f"{dilemma}\n\n---\n\n{session.transcript(cfg)}"
    closing = bc.sonnet(close_sys, close_user, temperature=0.5, max_tokens=400)
    _emit(session, Line(role="moderator_close", text=closing), on_line)

    return session
