#!/usr/bin/env python
"""output/ ディレクトリを走査してレポート一覧 index.html を生成する."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _ROOT / "output"
_INDEX = _ROOT / "index.html"

_DIR_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(_v\d+)?$")


def _collect_reports() -> list[dict]:
    reports = []
    if not _OUTPUT.exists():
        return reports
    for d in sorted(_OUTPUT.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        m = _DIR_PATTERN.match(d.name)
        if not m:
            continue
        dashboard = d / "dashboard.html"
        if not dashboard.exists():
            continue
        date_str = m.group(1)
        company = m.group(2)
        version = m.group(3) or ""
        reports.append({
            "date": date_str,
            "company": company + version,
            "path": f"output/{d.name}/dashboard.html",
        })
    return reports


def build(output_path: Path = _INDEX) -> Path:
    reports = _collect_reports()
    today = date.today().isoformat()

    rows = ""
    for r in reports:
        rows += (
            f'<tr>'
            f'<td>{r["date"]}</td>'
            f'<td><a href="{r["path"]}">{r["company"]}</a></td>'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企業調査レポート一覧</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif;
         max-width: 720px; margin: 0 auto; padding: 16px; background: #f5f5f5; }}
  h1 {{ font-size: 1.3rem; color: #333; }}
  p.updated {{ font-size: 0.8rem; color: #999; margin-top: -8px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.1); }}
  th {{ background: #2d7dd2; color: #fff; padding: 10px 14px; text-align: left; font-size: 0.85rem; }}
  td {{ padding: 10px 14px; border-bottom: 1px solid #eee; font-size: 0.95rem; }}
  tr:last-child td {{ border-bottom: none; }}
  a {{ color: #2d7dd2; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .fab {{
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 56px;
    height: 56px;
    border-radius: 50%;
    background: #1d9bf0;
    color: #fff;
    font-size: 1.6rem;
    line-height: 56px;
    text-align: center;
    box-shadow: 0 4px 14px rgba(0,0,0,.25);
    cursor: pointer;
    border: none;
    transition: background .15s, transform .15s, box-shadow .15s;
    z-index: 100;
    text-decoration: none;
    display: block;
  }}
  .fab:hover {{ background: #1a8cd8; transform: scale(1.08); box-shadow: 0 6px 20px rgba(0,0,0,.3); }}
  .fab:active {{ transform: scale(0.95); }}
  .fab-tooltip {{
    position: fixed;
    bottom: 90px;
    right: 24px;
    background: rgba(0,0,0,.75);
    color: #fff;
    font-size: 0.78rem;
    padding: 5px 10px;
    border-radius: 6px;
    white-space: nowrap;
    opacity: 0;
    pointer-events: none;
    transition: opacity .2s;
  }}
  .fab:hover + .fab-tooltip {{ opacity: 1; }}
</style>
</head>
<body>
<h1>📋 企業調査レポート一覧</h1>
<p class="updated">最終更新: {today}</p>
<table>
<thead><tr><th>調査日</th><th>企業名</th></tr></thead>
<tbody>
{rows}</tbody>
</table>
<a class="fab" href="https://claude.ai/code/session_01LHb1wK4NT9R2obTLpc5LRY" target="_blank" rel="noopener noreferrer" title="新規調査を開始">✏️</a>
<div class="fab-tooltip">新規調査を開始</div>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = build()
    print(f"[OK] index.html を生成しました: {path}")
