#!/usr/bin/env python
"""output/ ディレクトリを走査してレポート一覧 index.html を生成する."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_OUTPUT = _ROOT / "output"
_INDEX = _ROOT / "index.html"

_DIR_PATTERN = re.compile(r"^(\d{4}-\d{2}-\d{2})_(.+?)(_v\d+)?$")

# SVG アイコン定義
_TRASH_SVG = (
    '<svg viewBox="0 0 22 24" width="18" height="18" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="2" y="7" width="18" height="15" rx="3"/>'
    '<path d="M1 7h20"/>'
    '<path d="M8 7V4.5A1.5 1.5 0 0 1 9.5 3h3A1.5 1.5 0 0 1 14 4.5V7"/>'
    '<line x1="9" y1="12" x2="9" y2="18"/>'
    '<line x1="13" y1="12" x2="13" y2="18"/>'
    '</svg>'
)

_RESTORE_SVG = (
    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M3 12a9 9 0 1 0 2.64-6.36L3 8"/>'
    '<path d="M3 3v5h5"/>'
    '</svg>'
)


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
            "dir": d.name,
            "path": f"output/{d.name}/dashboard.html",
        })
    return reports


def build(output_path: Path = _INDEX) -> Path:
    reports = _collect_reports()
    today = date.today().isoformat()

    rows = ""
    for r in reports:
        rows += (
            f'<tr data-date="{r["date"]}" data-company="{r["company"]}" data-dir="{r["dir"]}">\n'
            f'  <td class="col-date">{r["date"]}</td>\n'
            f'  <td class="col-company"><a href="{r["path"]}">{r["company"]}</a></td>\n'
            f'  <td class="col-action">'
            f'<button class="del-btn action-btn" data-dir="{r["dir"]}" '
            f'onclick="deleteReport(this.dataset.dir)" title="削除">{_TRASH_SVG}</button>'
            f'<button class="restore-btn action-btn" data-dir="{r["dir"]}" '
            f'onclick="restoreReport(this.dataset.dir)" title="復元" style="display:none">{_RESTORE_SVG}</button>'
            f'</td>\n'
            f'</tr>\n'
        )

    html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>企業調査レポート一覧</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Hiragino Sans', sans-serif;
    max-width: 760px;
    margin: 0 auto;
    padding: 16px;
    background: #f5f5f5;
    color: #333;
  }}
  h1 {{ font-size: 1.3rem; color: #333; margin-bottom: 4px; }}
  .updated {{ font-size: 0.8rem; color: #999; margin-bottom: 14px; }}

  .controls {{
    background: #fff;
    border-radius: 10px;
    padding: 14px 16px;
    margin-bottom: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,.1);
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }}
  .controls input[type="text"] {{
    flex: 1 1 160px;
    padding: 7px 10px;
    border: 1px solid #ddd;
    border-radius: 6px;
    font-size: 0.92rem;
    outline: none;
  }}
  .controls input[type="text"]:focus {{ border-color: #2d7dd2; }}
  .date-range {{
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }}
  .date-range input[type="date"] {{
    padding: 7px 8px;
    border: 1px solid #ddd;
    border-radius: 6px;
    font-size: 0.88rem;
    outline: none;
    color: #333;
  }}
  .date-range input[type="date"]:focus {{ border-color: #2d7dd2; }}
  .date-range span {{ font-size: 0.85rem; color: #888; }}
  .count {{ font-size: 0.82rem; color: #888; white-space: nowrap; }}
  .btn-show-deleted {{
    font-size: 0.78rem;
    color: #aaa;
    background: none;
    border: 1px solid #ddd;
    border-radius: 5px;
    padding: 4px 10px;
    cursor: pointer;
    white-space: nowrap;
  }}
  .btn-show-deleted:hover {{ color: #666; border-color: #bbb; }}

  table {{
    width: 100%;
    border-collapse: collapse;
    background: #fff;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,.1);
  }}
  th {{
    background: #2d7dd2;
    color: #fff;
    padding: 10px 14px;
    text-align: left;
    font-size: 0.85rem;
    user-select: none;
  }}
  th.sortable {{ cursor: pointer; white-space: nowrap; }}
  th.sortable:hover {{ background: #2570c0; }}
  .sort-icon {{ margin-left: 4px; font-size: 0.75rem; }}
  td {{
    padding: 10px 14px;
    border-bottom: 1px solid #eee;
    font-size: 0.95rem;
    vertical-align: middle;
  }}
  tr:last-child td {{ border-bottom: none; }}
  tr.hidden-row {{ display: none; }}
  tr.deleted-row {{ opacity: 0.38; background: #fafafa; }}
  .col-date {{ white-space: nowrap; width: 110px; }}
  .col-action {{ width: 44px; text-align: center; }}
  a {{ color: #2d7dd2; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}

  .action-btn {{
    background: none;
    border: none;
    cursor: pointer;
    padding: 4px;
    border-radius: 6px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    transition: background .15s, transform .1s;
  }}
  .del-btn {{ color: #bbb; }}
  .del-btn:hover {{ color: #e55; background: #fff0f0; transform: scale(1.15); }}
  .restore-btn {{ color: #6cb; }}
  .restore-btn:hover {{ color: #2a9; background: #f0fff8; transform: scale(1.15); }}

  .no-results {{
    text-align: center;
    padding: 28px;
    color: #aaa;
    font-size: 0.9rem;
    display: none;
  }}

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

  @media (max-width: 500px) {{
    .controls {{ gap: 8px; }}
    .date-range {{ width: 100%; }}
    .date-range input[type="date"] {{ flex: 1; min-width: 0; }}
  }}
</style>
</head>
<body>
<h1>📋 企業調査レポート一覧</h1>
<p class="updated">最終更新: {today}</p>

<div class="controls">
  <input type="text" id="search-company" placeholder="企業名で検索..." oninput="applyFilter()">
  <div class="date-range">
    <input type="date" id="from-date" oninput="applyFilter()">
    <span>〜</span>
    <input type="date" id="to-date" oninput="applyFilter()">
  </div>
  <span class="count" id="count-label"></span>
  <button class="btn-show-deleted" id="toggle-deleted" onclick="toggleDeleted()">削除済みを表示</button>
</div>

<table id="report-table">
<thead>
  <tr>
    <th class="sortable col-date" onclick="toggleSort()">
      調査日<span class="sort-icon" id="sort-icon">▼</span>
    </th>
    <th>企業名</th>
    <th></th>
  </tr>
</thead>
<tbody id="tbody">
{rows}</tbody>
</table>
<p class="no-results" id="no-results">該当する調査結果がありません</p>

<a class="fab" href="https://claude.ai/code/session_01LHb1wK4NT9R2obTLpc5LRY" target="_blank" rel="noopener noreferrer" title="新規調査を開始">✏️</a>
<div class="fab-tooltip">新規調査を開始</div>

<script>
const STORAGE_KEY = 'deleted_reports';
let sortDesc = true;
let showDeleted = false;

function getDeleted() {{
  return new Set(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]'));
}}
function saveDeleted(set) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]));
}}

function deleteReport(dir) {{
  if (!confirm('この調査結果を一覧から非表示にしますか？')) return;
  const del = getDeleted();
  del.add(dir);
  saveDeleted(del);
  applyFilter();
}}

function restoreReport(dir) {{
  const del = getDeleted();
  del.delete(dir);
  saveDeleted(del);
  applyFilter();
}}

function toggleDeleted() {{
  showDeleted = !showDeleted;
  document.getElementById('toggle-deleted').textContent =
    showDeleted ? '削除済みを隠す' : '削除済みを表示';
  applyFilter();
}}

function toggleSort() {{
  sortDesc = !sortDesc;
  document.getElementById('sort-icon').textContent = sortDesc ? '▼' : '▲';
  const tbody = document.getElementById('tbody');
  const rows = [...tbody.querySelectorAll('tr')];
  rows.sort((a, b) => {{
    const da = a.dataset.date, db = b.dataset.date;
    return sortDesc ? db.localeCompare(da) : da.localeCompare(db);
  }});
  rows.forEach(r => tbody.appendChild(r));
  updateCount();
}}

function applyFilter() {{
  const q = document.getElementById('search-company').value.trim().toLowerCase();
  const from = document.getElementById('from-date').value;
  const to = document.getElementById('to-date').value;
  const del = getDeleted();
  const rows = document.querySelectorAll('#tbody tr');
  let visible = 0;

  rows.forEach(row => {{
    const dir = row.dataset.dir;
    const company = row.dataset.company.toLowerCase();
    const d = row.dataset.date;
    const isDel = del.has(dir);

    const matchQ  = !q    || company.includes(q);
    const matchFrom = !from || d >= from;
    const matchTo   = !to   || d <= to;
    const show = matchQ && matchFrom && matchTo && (showDeleted || !isDel);

    row.classList.toggle('hidden-row',   !show);
    row.classList.toggle('deleted-row',  isDel && show);
    if (show) visible++;

    // ボタン切り替え
    const delBtn     = row.querySelector('.del-btn');
    const restoreBtn = row.querySelector('.restore-btn');
    if (isDel) {{
      delBtn.style.display     = 'none';
      restoreBtn.style.display = '';
    }} else {{
      delBtn.style.display     = '';
      restoreBtn.style.display = 'none';
    }}
  }});

  document.getElementById('count-label').textContent = visible + ' 件';
  document.getElementById('no-results').style.display = visible === 0 ? 'block' : 'none';
}}

function updateCount() {{
  const visible = [...document.querySelectorAll('#tbody tr')]
    .filter(r => !r.classList.contains('hidden-row')).length;
  document.getElementById('count-label').textContent = visible + ' 件';
}}

applyFilter();
</script>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = build()
    print(f"[OK] index.html を生成しました: {path}")
