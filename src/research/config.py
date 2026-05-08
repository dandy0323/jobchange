"""設定・パス・定数."""

from __future__ import annotations

import os
from pathlib import Path

# プロジェクトルート = 本ファイルの3つ上
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR: Path = PROJECT_ROOT / "output"
TEMPLATES_DIR: Path = PROJECT_ROOT / "templates"
PROMPTS_DIR: Path = PROJECT_ROOT / "prompts"
SKILLS_DIR: Path = PROJECT_ROOT / ".claude" / "skills"

# モデル選択のエイリアス
MODEL_ALIASES: dict[str, str] = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}
DEFAULT_MODEL: str = os.getenv("COMPANY_RESEARCH_MODEL", "claude-sonnet-4-6")


def resolve_model(name: str) -> str:
    """`sonnet` / `opus` / `haiku` のエイリアスを実モデルIDへ解決."""
    return MODEL_ALIASES.get(name, name)
