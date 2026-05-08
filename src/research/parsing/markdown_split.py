"""Agent 応答からMarkdown本文とJSONブロックを分離するユーティリティ."""

from __future__ import annotations

import json
import re
from typing import Any


# ```json ... ``` / ```JSON ... ``` の fenced code block
_JSON_BLOCK_RE = re.compile(
    r"```(?:json|JSON|Json)\s*\n(?P<body>.*?)\n```",
    re.DOTALL,
)

# 末尾カンマ（`,}` / `,]`）を除去する緩いフィクサー
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _try_parse_json(raw: str) -> Any | None:
    """厳密パース→失敗時は軽いクリーンアップしてリトライ."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # 末尾カンマの除去
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # JavaScriptスタイルのコメント除去 ("// ..." / "/* ... */")
    cleaned = re.sub(r"//[^\n]*", "", cleaned)
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


def split_markdown_and_json(text: str) -> tuple[str, dict | None]:
    """応答テキストから末尾の ```json ... ``` を抽出.

    Returns:
        (JSON ブロックを除去した Markdown, パース済みJSON辞書 or None)

    JSON ブロックが複数あれば末尾のものを優先する。
    パースに失敗した場合は Markdown は原文のまま、JSON は None で返す。
    """
    matches = list(_JSON_BLOCK_RE.finditer(text))
    if not matches:
        return text, None

    # 末尾ブロックを優先
    last = matches[-1]
    raw = last.group("body").strip()
    data = _try_parse_json(raw)

    if data is None:
        # パース失敗 → Markdown はそのまま返す（保存できないより見える方がマシ）
        return text, None

    if not isinstance(data, dict):
        return text, None

    # Markdown からこのブロックだけ除去。前後の空白を詰めつつ改行を保つ。
    before = text[: last.start()].rstrip()
    after = text[last.end() :].lstrip()
    parts = [p for p in (before, after) if p]
    markdown_only = "\n\n".join(parts) + ("\n" if parts else "")

    return markdown_only, data
