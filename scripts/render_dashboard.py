#!/usr/bin/env python
"""output_dir 内の report_*.md / data.json からダッシュボードHTMLを生成して開く.

使い方 (企業調査-フル Skill の末尾で呼ばれる):
    python scripts/render_dashboard.py --output-dir output/2026-04-17_XXX --company "XXX"

オプション:
    --output-dir  出力ディレクトリ (report_basic.md 等が存在するパス) [必須]
    --company     企業名 [必須]
    --model       モデル名 (表示用, デフォルト: claude-code-chat)
    --no-open     ブラウザを開かない
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# src/ をパスに追加（どのディレクトリから呼ばれても動くように）
_HERE = Path(__file__).resolve()
_SRC = _HERE.parent.parent / "src"
sys.path.insert(0, str(_SRC))

from research.render.html import rebuild_dashboard  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="ダッシュボードHTMLを再生成")
    parser.add_argument("--output-dir", required=True, help="出力ディレクトリのパス")
    parser.add_argument("--company", required=True, help="企業名")
    parser.add_argument("--model", default="claude-code-chat", help="モデル名（表示用）")
    parser.add_argument("--no-open", action="store_true", help="ブラウザを開かない")
    args = parser.parse_args()

    output_dir = Path(args.output_dir).resolve()
    if not output_dir.exists():
        print(f"[error] ディレクトリが存在しません: {output_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"ダッシュボードを生成中: {output_dir}")
    dashboard_path = rebuild_dashboard(
        output_dir=output_dir,
        company=args.company,
        model=args.model,
    )
    print(f"[OK] 生成完了: {dashboard_path}")

    if not args.no_open:
        try:
            if sys.platform == "win32":
                os.startfile(str(dashboard_path))
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(dashboard_path)])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", str(dashboard_path)])
        except Exception as exc:
            print(f"[warn] ブラウザを開けませんでした: {exc}", file=sys.stderr)
            import webbrowser
            webbrowser.open(dashboard_path.as_uri())


if __name__ == "__main__":
    main()
