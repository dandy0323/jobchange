"""HTMLダッシュボードレンダラー.

Phase 1.5: ヒーロースクリーニング / TOC / 出典脚注化 / セクション配色 /
タイポグラフィ / コンパクト表示切替 をサポートする見栄え強化版。

Markdownの軽量パースのみで動き、構造化JSONに依存しない。
"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from research.config import TEMPLATES_DIR
from research.parsing.schema import ReportData


# ---------------------------------------------------------------------------
# データクラス
# ---------------------------------------------------------------------------


@dataclass
class ScreeningCard:
    """総合スクリーニング結果の1行（観点/判定/概要）."""

    axis: str
    badge: str  # 🟢🟡🔴⚪
    level_label: str  # "懸念なし" 等
    summary: str


@dataclass
class Source:
    """出典1件."""

    num: int
    title: str
    url: str


@dataclass
class ProcessedSection:
    """1つのレポートMarkdownから抽出された成果物."""

    html: str
    screening: list[ScreeningCard] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Jinja2
# ---------------------------------------------------------------------------


def _make_env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "htm", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ---------------------------------------------------------------------------
# 前処理: Agent の前置き文を除去
# ---------------------------------------------------------------------------


def _strip_agent_preamble(md: str) -> str:
    """Agent の前置き（「承知しました」「ファイルの保存が完了…」等）を除去.

    `# ` または `---` から始まる行以降を本文とみなす。
    """
    lines = md.splitlines()
    start = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        # 最初に登場する `#` 始まりを本文の先頭とする
        if stripped.startswith("# ") or stripped.startswith("## "):
            start = i
            break
        # `---` 区切りから始まるパターン
        if stripped == "---" and i + 1 < len(lines):
            # `---` の直後に `#` が来るなら本文開始
            for j in range(i + 1, min(i + 4, len(lines))):
                if lines[j].strip().startswith("#"):
                    start = j
                    break
            if start:
                break
    return "\n".join(lines[start:]).lstrip()


# ---------------------------------------------------------------------------
# 総合スクリーニング抽出
# ---------------------------------------------------------------------------


_BADGE_TO_LABEL = {
    "🟢": "懸念なし",
    "🟡": "要確認",
    "🔴": "重大懸念",
    "⚪": "情報なし",
}

_BADGE_CHARS = set(_BADGE_TO_LABEL.keys())


def _extract_screening(md: str) -> tuple[str, list[ScreeningCard]]:
    """`## 総合スクリーニング` セクションをMarkdownから抜き出す.

    Returns:
        (screening を除去した Markdown, ScreeningCard のリスト)
    """
    lines = md.splitlines()
    n = len(lines)
    cards: list[ScreeningCard] = []

    # スクリーニング見出しを検索
    heading_idx = -1
    for i, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+.*(総合スクリーニング|スクリーニング結果)", line):
            heading_idx = i
            break

    if heading_idx == -1:
        return md, []

    # 見出しの次に来るテーブルを探す
    table_start = -1
    for i in range(heading_idx + 1, min(heading_idx + 10, n)):
        if "|" in lines[i] and i + 1 < n and re.match(r"^\s*\|[\s\|:\-]+\|\s*$", lines[i + 1]):
            table_start = i
            break

    if table_start == -1:
        return md, []

    # テーブルをパース
    header_cells = [c.strip() for c in lines[table_start].strip().strip("|").split("|")]
    try:
        axis_idx = next(i for i, h in enumerate(header_cells) if "観点" in h or "項目" in h)
        judge_idx = next(i for i, h in enumerate(header_cells) if "判定" in h or "評価" in h)
    except StopIteration:
        return md, []
    summary_idx = None
    for i, h in enumerate(header_cells):
        if "概要" in h or "サマリ" in h or "コメント" in h:
            summary_idx = i
            break

    # データ行
    row_idx = table_start + 2  # ヘッダ + セパレータ
    while row_idx < n and "|" in lines[row_idx] and lines[row_idx].strip():
        cells = [c.strip() for c in lines[row_idx].strip().strip("|").split("|")]
        if len(cells) > max(axis_idx, judge_idx):
            badge = ""
            for ch in cells[judge_idx]:
                if ch in _BADGE_CHARS:
                    badge = ch
                    break
            cards.append(
                ScreeningCard(
                    axis=cells[axis_idx],
                    badge=badge,
                    level_label=_BADGE_TO_LABEL.get(badge, "—"),
                    summary=cells[summary_idx] if summary_idx is not None and len(cells) > summary_idx else "",
                )
            )
        row_idx += 1

    # テーブル直後に続く「判定基準」blockquote もまとめて削除
    remove_end = row_idx
    while remove_end < n and (
        lines[remove_end].strip().startswith(">")
        or lines[remove_end].strip() == ""
        or lines[remove_end].strip() == "---"
    ):
        remove_end += 1
        # 空行連続で止める
        if remove_end < n and lines[remove_end].strip() == "" and lines[remove_end - 1].strip() == "":
            break

    # 見出し直前の「---」も吸収
    remove_start = heading_idx
    if remove_start > 0 and lines[remove_start - 1].strip() == "---":
        remove_start -= 1

    new_md = "\n".join(lines[:remove_start] + lines[remove_end:])
    return new_md, cards


# ---------------------------------------------------------------------------
# 出典の脚注化
# ---------------------------------------------------------------------------


_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")


def _normalize_url_title(title: str) -> str:
    return title.strip()


def _extract_sources(md: str) -> tuple[str, list[Source]]:
    """Markdown内の `[text](url)` を `text[N]` 形式に置換し、出典リストを収集.

    同じURLには同じ番号を割り当てる。
    """
    url_to_num: dict[str, int] = {}
    url_to_title: dict[str, str] = {}
    order: list[str] = []

    def repl(m: re.Match[str]) -> str:
        text = _normalize_url_title(m.group(1))
        url = m.group(2).rstrip(").,;")
        if url not in url_to_num:
            num = len(url_to_num) + 1
            url_to_num[url] = num
            url_to_title[url] = text
            order.append(url)
        n = url_to_num[url]
        # 目印として独自マーカーを残す。後段でHTML化時に変換。
        return f"{text}\x00FN:{n}\x00"

    new_md = _MD_LINK_RE.sub(repl, md)

    sources = [
        Source(num=url_to_num[u], title=url_to_title[u], url=u) for u in order
    ]
    return new_md, sources


# ---------------------------------------------------------------------------
# Markdown → HTML 変換
# ---------------------------------------------------------------------------


_BADGE_MAP = {
    "🟢": '<span class="badge badge-green">🟢</span>',
    "🟡": '<span class="badge badge-yellow">🟡</span>',
    "🔴": '<span class="badge badge-red">🔴</span>',
    "⚪": '<span class="badge badge-gray">⚪</span>',
    "✅": '<span class="badge badge-green">✅</span>',
    "⚠️": '<span class="badge badge-yellow">⚠️</span>',
    "❓": '<span class="badge badge-gray">❓</span>',
    "❌": '<span class="badge badge-red">❌</span>',
}

_URL_PATTERN = re.compile(r"(?<!['\"=>])((?:https?://)[^\s\)\]\"'<>]+)")


def _linkify_bare_urls(text: str) -> str:
    """裸URLを<a>化 (既にaタグの中は除く)."""
    return _URL_PATTERN.sub(
        r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )


def _slugify(text: str) -> str:
    """見出しテキストからHTMLのid用スラグを生成."""
    text = unicodedata.normalize("NFKC", text)
    # 絵文字・記号を除去
    text = re.sub(r"[^\w一-龯ぁ-んァ-ヶー]+", "-", text).strip("-")
    return text[:60] or "section"


def _markdown_to_html(md: str) -> str:
    """軽量Markdown→HTML変換."""
    escaped = html_lib.escape(md)

    # 脚注マーカーを復元（エスケープされている可能性はない、\x00 は escape されない）
    # FN:N → <sup class="fnref"><a href="#src-N">[N]</a></sup>
    escaped = re.sub(
        r"\x00FN:(\d+)\x00",
        r'<sup class="fnref"><a href="#src-\1">[\1]</a></sup>',
        escaped,
    )

    # 裸URLをリンク化
    lines_out: list[str] = []
    for line in escaped.split("\n"):
        if "<a " in line:
            lines_out.append(line)
        else:
            lines_out.append(_linkify_bare_urls(line))
    escaped = "\n".join(lines_out)

    # 見出し
    escaped = re.sub(r"^### (.+)$", r"<h3>\1</h3>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^## (.+)$", r"<h2>\1</h2>", escaped, flags=re.MULTILINE)
    escaped = re.sub(r"^# (.+)$", r"<h1>\1</h1>", escaped, flags=re.MULTILINE)

    # 太字・強調
    escaped = re.sub(r"\*\*([^\*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<!\*)\*([^\*]+)\*(?!\*)", r"<em>\1</em>", escaped)

    # バッジ変換
    for src, dst in _BADGE_MAP.items():
        escaped = escaped.replace(src, dst)

    # テーブル変換
    escaped = _convert_tables(escaped)

    # リスト
    escaped = _convert_lists(escaped)

    # ブロック引用
    escaped = re.sub(r"^&gt; (.+)$", r"<blockquote>\1</blockquote>", escaped, flags=re.MULTILINE)

    # 水平線
    escaped = re.sub(r"^---$", r"<hr>", escaped, flags=re.MULTILINE)

    # 段落化
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", escaped):
        block = block.strip()
        if not block:
            continue
        if re.match(r"^<(h[1-6]|ul|ol|table|blockquote|hr|pre|div|section)", block):
            blocks.append(block)
        else:
            blocks.append(f"<p>{block}</p>")
    html = "\n\n".join(blocks)

    # 見出しに id 付与
    html = _add_heading_ids(html)
    return html


def _convert_tables(text: str) -> str:
    """Markdownパイプテーブル → <table class="data-table">."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|[\s\|:\-]+\|\s*$", lines[i + 1]):
            header_cells = [c.strip() for c in line.strip().strip("|").split("|")]
            i += 2
            rows: list[list[str]] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            t = ['<table class="data-table">', "<thead><tr>"]
            for h in header_cells:
                t.append(f"<th>{h}</th>")
            t.append("</tr></thead><tbody>")
            for row in rows:
                t.append("<tr>")
                for cell in row:
                    t.append(f"<td>{cell}</td>")
                t.append("</tr>")
            t.append("</tbody></table>")
            out.append("".join(t))
        else:
            out.append(line)
            i += 1
    return "\n".join(out)


def _convert_lists(text: str) -> str:
    """連続する `- ` / `* ` 行を <ul> へ変換."""
    lines = text.split("\n")
    out: list[str] = []
    current: list[str] = []

    def flush():
        if current:
            out.append("<ul>")
            for item in current:
                out.append(f"<li>{item}</li>")
            out.append("</ul>")
            current.clear()

    for line in lines:
        m = re.match(r"^\s*[-*] (.+)$", line)
        if m:
            current.append(m.group(1))
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out)


# ---------------------------------------------------------------------------
# 見出しID付与 & セクション配色
# ---------------------------------------------------------------------------


def _add_heading_ids(html: str) -> str:
    """h2/h3 に id を付与。同名衝突は -2, -3 で採番。"""
    used: dict[str, int] = {}

    def repl(m: re.Match[str]) -> str:
        tag = m.group(1)
        inner = m.group(2)
        # インナーのタグを除いたテキストでスラグ
        text_only = re.sub(r"<[^>]+>", "", inner)
        base = _slugify(text_only)
        n = used.get(base, 0) + 1
        used[base] = n
        slug = base if n == 1 else f"{base}-{n}"
        # セクション配色: h2 内に 🟢🟡🔴 があれば data-badge
        badge = ""
        for ch in text_only:
            if ch in _BADGE_CHARS:
                badge = ch
                break
        data_attr = f' data-badge="{badge}"' if badge else ""
        return f'<{tag} id="{slug}"{data_attr}>{inner}</{tag}>'

    return re.sub(r"<(h[23])>(.+?)</\1>", repl, html, flags=re.DOTALL)


def _apply_section_accents_from_screening(
    html: str, screening: list[ScreeningCard]
) -> str:
    """screening カードの axis 名に一致する h2 にアクセント色クラスを付与."""
    if not screening:
        return html

    badge_to_class = {"🟢": "accent-green", "🟡": "accent-yellow", "🔴": "accent-red", "⚪": "accent-gray"}

    def match_axis(h2_text: str) -> str | None:
        clean = re.sub(r"<[^>]+>", "", h2_text)
        for card in screening:
            # 最初の2文字が含まれていれば一致とみなす
            key = card.axis.strip()
            # 「・」で区切った最初の要素で判定
            first_token = key.split("・")[0].split("/")[0][:4]
            if first_token and first_token in clean:
                return badge_to_class.get(card.badge)
        return None

    def repl(m: re.Match[str]) -> str:
        attrs = m.group(1) or ""
        inner = m.group(2)
        cls = match_axis(inner)
        if not cls:
            return m.group(0)
        if 'class="' in attrs:
            attrs = attrs.replace('class="', f'class="{cls} ')
        else:
            attrs = f' class="{cls}"' + attrs
        return f"<h2{attrs}>{inner}</h2>"

    return re.sub(r"<h2([^>]*)>(.+?)</h2>", repl, html, flags=re.DOTALL)


# ---------------------------------------------------------------------------
# 出典一覧ブロックの生成
# ---------------------------------------------------------------------------


def _render_sources_block(sources: list[Source]) -> str:
    if not sources:
        return ""
    rows = []
    for s in sources:
        rows.append(
            f'<tr id="src-{s.num}">'
            f'<td class="src-num">[{s.num}]</td>'
            f'<td class="src-title">{html_lib.escape(s.title)}</td>'
            f'<td class="src-url"><a href="{html_lib.escape(s.url)}" '
            f'target="_blank" rel="noopener noreferrer">{html_lib.escape(s.url)}</a></td>'
            f"</tr>"
        )
    body = "".join(rows)
    return (
        '<section class="sources-section">'
        '<h2 class="sources-title">📚 出典一覧</h2>'
        '<table class="sources-table">'
        "<thead><tr><th>No.</th><th>タイトル</th><th>URL</th></tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
        "</section>"
    )


# ---------------------------------------------------------------------------
# パイプライン: Markdown → ProcessedSection
# ---------------------------------------------------------------------------


def _process_markdown(md: str, *, extract_screening: bool) -> ProcessedSection:
    md = _strip_agent_preamble(md)
    screening: list[ScreeningCard] = []
    if extract_screening:
        md, screening = _extract_screening(md)
    md, sources = _extract_sources(md)
    html = _markdown_to_html(md)
    html = _apply_section_accents_from_screening(html, screening)
    html += _render_sources_block(sources)
    return ProcessedSection(html=html, screening=screening, sources=sources)


# ---------------------------------------------------------------------------
# パブリック: ダッシュボード生成
# ---------------------------------------------------------------------------


def _screening_from_report(report_data: ReportData) -> list[ScreeningCard]:
    """pydantic `ReportData.screening` を ScreeningCard に変換."""
    cards: list[ScreeningCard] = []
    for j in report_data.screening:
        cards.append(
            ScreeningCard(
                axis=j.axis,
                badge=j.badge,
                level_label=j.level_label or _BADGE_TO_LABEL.get(j.badge, "—"),
                summary=j.summary,
            )
        )
    return cards


# ---------------------------------------------------------------------------
# 面接質問タブの描画
# ---------------------------------------------------------------------------


def _render_interview_questions_section(report_data: ReportData) -> str:
    """`interview_questions` を専用タブのHTMLへ変換.

    - 上部にカテゴリフィルタチップ（クリックで絞り込み）
    - 各質問はカード形式（カテゴリバッジ・質問文・理由・コピーボタン）
    """
    questions = report_data.interview_questions
    if not questions:
        return (
            '<div class="empty-questions">'
            '<p>面接質問は構造化データに含まれていませんでした。</p>'
            '</div>'
        )

    # カテゴリ一覧を順序保持しつつ抽出
    categories: list[str] = []
    for q in questions:
        c = (q.category or "その他").strip() or "その他"
        if c not in categories:
            categories.append(c)

    # フィルタチップ
    chips = ['<button type="button" class="q-filter-chip active" data-filter="__all__">すべて</button>']
    for c in categories:
        safe_c = html_lib.escape(c)
        chips.append(
            f'<button type="button" class="q-filter-chip" data-filter="{safe_c}">'
            f"{safe_c}"
            "</button>"
        )
    chips_html = "".join(chips)

    # 質問カード
    cards: list[str] = []
    for idx, q in enumerate(questions, start=1):
        category = html_lib.escape((q.category or "その他").strip() or "その他")
        text = html_lib.escape(q.question)
        rationale = html_lib.escape(q.rationale or "")
        rationale_block = (
            f'<p class="q-rationale">💡 {rationale}</p>' if rationale else ""
        )
        # data-copy に生の質問文を保持（HTMLエスケープはしない。data属性の " をエスケープだけ）
        copy_payload = q.question.replace('"', "&quot;")
        cards.append(
            f'<article class="q-card" data-category="{category}">'
            f'<div class="q-card-head">'
            f'<span class="q-num">Q{idx}</span>'
            f'<span class="q-category-badge">{category}</span>'
            f'<button type="button" class="q-copy-btn" data-copy="{copy_payload}" '
            f'title="質問をコピー">📋 コピー</button>'
            f"</div>"
            f'<p class="q-text">{text}</p>'
            f"{rationale_block}"
            "</article>"
        )

    return (
        '<section class="interview-questions">'
        f'<p class="q-intro">面接で聞きたい質問を {len(questions)} 件整理しました。'
        'カテゴリでの絞り込み・ワンクリックコピーに対応しています。</p>'
        f'<div class="q-filter-bar" role="tablist">{chips_html}</div>'
        f'<div class="q-card-list">{"".join(cards)}</div>'
        "</section>"
    )


# ---------------------------------------------------------------------------
# 求人票整合性タブの描画 (Phase 4)
# ---------------------------------------------------------------------------


_INTEGRITY_TO_CLASS = {
    "✅": "ok",
    "⚠️": "warn",
    "❓": "unknown",
}

_INTEGRITY_TO_LABEL = {
    "✅": "整合",
    "⚠️": "要確認",
    "❓": "不明",
}


def _render_job_fit_section(report_data: ReportData) -> str:
    """求人票整合性タブのHTML."""
    rows = report_data.job_fit
    additional = report_data.additional_considerations

    if not rows and not additional:
        return (
            '<div class="empty-questions">'
            '<p>求人票整合性データがありません。</p>'
            '</div>'
        )

    # 整合性サマリ（件数カウント）
    counts = {"✅": 0, "⚠️": 0, "❓": 0}
    for r in rows:
        counts[r.integrity] = counts.get(r.integrity, 0) + 1

    summary_cards_html = ""
    if rows:
        summary_cards_html = (
            '<div class="jfit-summary">'
            f'<div class="jfit-summary-card jfit-summary-ok">'
            f'<span class="jfit-summary-icon">✅</span>'
            f'<span class="jfit-summary-num">{counts["✅"]}</span>'
            f'<span class="jfit-summary-label">整合</span></div>'
            f'<div class="jfit-summary-card jfit-summary-warn">'
            f'<span class="jfit-summary-icon">⚠️</span>'
            f'<span class="jfit-summary-num">{counts["⚠️"]}</span>'
            f'<span class="jfit-summary-label">要確認</span></div>'
            f'<div class="jfit-summary-card jfit-summary-unknown">'
            f'<span class="jfit-summary-icon">❓</span>'
            f'<span class="jfit-summary-num">{counts["❓"]}</span>'
            f'<span class="jfit-summary-label">不明</span></div>'
            '</div>'
        )

    # テーブル
    table_html = ""
    if rows:
        body_rows: list[str] = []
        for r in rows:
            cls = _INTEGRITY_TO_CLASS.get(r.integrity, "")
            label = _INTEGRITY_TO_LABEL.get(r.integrity, "—")
            note_html = html_lib.escape(r.note) if r.note else "—"
            body_rows.append(
                f'<tr class="jfit-row jfit-row-{cls}">'
                f'<td class="jfit-claim">{html_lib.escape(r.claim)}</td>'
                f'<td class="jfit-finding">{html_lib.escape(r.finding)}</td>'
                f'<td class="jfit-integrity">'
                f'<span class="jfit-badge jfit-badge-{cls}">{r.integrity} {label}</span>'
                f'</td>'
                f'<td class="jfit-note">{note_html}</td>'
                '</tr>'
            )
        table_html = (
            '<div class="jfit-table-wrapper">'
            '<table class="jfit-table">'
            '<thead><tr>'
            '<th>求人票の記載</th>'
            '<th>調査で確認できた実態</th>'
            '<th>整合性</th>'
            '<th>備考</th>'
            '</tr></thead>'
            f'<tbody>{"".join(body_rows)}</tbody>'
            '</table>'
            '</div>'
        )

    # 追加留意事項
    notes_html = ""
    if additional:
        items = "".join(
            f'<li>{html_lib.escape(n)}</li>' for n in additional
        )
        notes_html = (
            '<section class="jfit-notes">'
            '<h3 class="jfit-notes-title">💡 面接で確認すべき追加事項</h3>'
            f'<ul class="jfit-notes-list">{items}</ul>'
            '</section>'
        )

    return (
        '<section class="job-fit">'
        '<p class="jfit-intro">'
        '求人票の記載内容と Web 調査で確認できた実態の整合性をチェックしました。'
        '⚠️ は差異がある項目、❓ は公開情報で確認困難な項目です。'
        '</p>'
        f'{summary_cards_html}'
        f'{table_html}'
        f'{notes_html}'
        '</section>'
    )


def render_simple_dashboard(
    *,
    output_dir: Path,
    company: str,
    basic_md: str | None,
    detail_md: str | None,
    model: str,
    report_data: ReportData | None = None,
) -> Path:
    """ダッシュボード HTML を生成.

    `report_data` が与えられた場合は pydantic 検証済みの構造化データから
    ヒーロースクリーニングを構築する（信頼性優先）。無ければ Markdown 抽出に
    フォールバック。
    """
    env = _make_env()
    template = env.get_template("dashboard.html.j2")

    sections = []

    # hero screening の優先順: 1) report_data.screening, 2) Markdown 抽出
    hero_screening: list[ScreeningCard] = []
    use_structured = False
    if report_data and report_data.screening:
        hero_screening = _screening_from_report(report_data)
        use_structured = True

    if basic_md:
        # 構造化データがあるなら Markdown 側での抽出はスキップ
        # （本文のスクリーニング表は Markdown として残すだけで、ヒーローは構造化優先）
        processed = _process_markdown(
            basic_md,
            extract_screening=not use_structured,
        )
        if not use_structured and processed.screening:
            hero_screening = processed.screening
        sections.append(
            {
                "id": "basic",
                "label": "基本調査",
                "html": processed.html,
            }
        )
    if detail_md:
        processed = _process_markdown(detail_md, extract_screening=False)
        sections.append(
            {
                "id": "detail",
                "label": "詳細調査",
                "html": processed.html,
            }
        )

    # 求人票整合性タブ (Phase 4)
    if report_data and (report_data.job_fit or report_data.additional_considerations):
        sections.append(
            {
                "id": "job-fit",
                "label": f"📋 求人票整合性 ({len(report_data.job_fit)})",
                "html": _render_job_fit_section(report_data),
            }
        )

    # 面接質問タブ（構造化データがある場合のみ）
    if report_data and report_data.interview_questions:
        sections.append(
            {
                "id": "questions",
                "label": f"💬 面接質問 ({len(report_data.interview_questions)})",
                "html": _render_interview_questions_section(report_data),
            }
        )

    rendered = template.render(
        company=company,
        surveyed_at=date.today().isoformat(),
        model=model,
        sections=sections,
        hero_screening=hero_screening,
        data_source=("structured" if use_structured else "markdown"),
    )

    dashboard_path = output_dir / "dashboard.html"
    dashboard_path.write_text(rendered, encoding="utf-8")

    # アセットコピー
    assets_src = TEMPLATES_DIR / "assets"
    if assets_src.exists():
        for asset in assets_src.iterdir():
            if asset.is_file():
                (output_dir / asset.name).write_bytes(asset.read_bytes())

    return dashboard_path


# ---------------------------------------------------------------------------
# 既存の output ディレクトリからダッシュボードを再生成するヘルパ
# ---------------------------------------------------------------------------


def rebuild_dashboard(output_dir: Path, *, company: str, model: str) -> Path:
    """既存の `report_basic.md` / `report_detail.md` / `data.json` から HTML のみ再生成."""
    import json as _json

    from research.parsing.markdown_split import split_markdown_and_json

    basic_path = output_dir / "report_basic.md"
    detail_path = output_dir / "report_detail.md"
    data_json_path = output_dir / "data.json"

    basic_md = basic_path.read_text(encoding="utf-8") if basic_path.exists() else None
    detail_md_raw = detail_path.read_text(encoding="utf-8") if detail_path.exists() else None

    # detail_md 末尾の ```json ``` ブロックを除去し、JSONデータを抽出する
    detail_md: str | None = None
    extracted_json: dict | None = None
    if detail_md_raw is not None:
        detail_md, extracted_json = split_markdown_and_json(detail_md_raw)

    report_data: ReportData | None = None

    # 優先順位: data.json > detail_md 内の JSON ブロック
    if data_json_path.exists():
        try:
            raw = _json.loads(data_json_path.read_text(encoding="utf-8"))
            report_data = ReportData.model_validate(raw)
        except Exception:
            report_data = None

    if report_data is None and extracted_json is not None:
        try:
            report_data = ReportData.model_validate(extracted_json)
        except Exception:
            report_data = None

    return render_simple_dashboard(
        output_dir=output_dir,
        company=company,
        basic_md=basic_md,
        detail_md=detail_md,
        model=model,
        report_data=report_data,
    )
