"""Assemble Lambda deployment bundles into build/<name>/.

Each bundle includes:
  - the lambda's handler module
  - the backend.shared package
  - any sibling modules the handler imports (e.g. conductor/core.py for the
    conductor Lambda, personas.py, bedrock_client.py, personas.json)

We keep it explicit rather than copying the whole backend tree so every
Lambda is as small as possible.

Usage:
    python -m scripts.build_lambdas
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


_SHARED = [
    "backend/__init__.py",
    "backend/shared/__init__.py",
    "backend/shared/config.py",
    "backend/shared/storage.py",
    "backend/conductor/__init__.py",
    "backend/conductor/personas.py",
    "personas.json",
]

BUNDLES: dict[str, list[str]] = {
    "ingest": _SHARED + [
        "backend/ingest/__init__.py",
        "backend/ingest/handler.py",
    ],
    "conductor": _SHARED + [
        "backend/shared/audio.py",
        "backend/conductor/bedrock_client.py",
        "backend/conductor/core.py",
        "backend/conductor/lambda_handler.py",
        "backend/ws/__init__.py",
        "backend/ws/handler.py",
    ],
    "api": _SHARED + [
        "backend/api/__init__.py",
        "backend/api/handler.py",
    ],
    "ws": _SHARED + [
        "backend/ws/__init__.py",
        "backend/ws/handler.py",
    ],
    "eval_worker": _SHARED + [
        "backend/conductor/bedrock_client.py",
        "backend/conductor/eval.py",
        "backend/eval_worker/__init__.py",
        "backend/eval_worker/handler.py",
    ],
}


def _build(name: str, files: list[str]) -> Path:
    out = BUILD / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel in files:
        src = ROOT / rel
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    return out


def main() -> int:
    if not BUILD.exists():
        BUILD.mkdir()
    for name, files in BUNDLES.items():
        path = _build(name, files)
        size_kb = sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) / 1024
        print(f"✓ build/{name}/  ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
