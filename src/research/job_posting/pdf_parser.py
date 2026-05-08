"""PDFファイルからテキストを抽出する (pymupdf ベース)."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

try:
    import pymupdf  # type: ignore
except ImportError:  # pragma: no cover
    pymupdf = None  # type: ignore


# スキャンPDF判定の閾値: 1ページあたりこの文字数未満なら「抽出量が乏しい」と判定
_SCANNED_PAGE_CHAR_THRESHOLD = 100


def extract_pdf_text(path: Path, console: Console) -> str | None:
    """PDF からテキストを抽出.

    Returns:
        抽出したテキスト。取得できなかった場合は None。

    警告:
        半数以上のページでテキスト量が乏しい場合、スキャンPDFの疑いがある旨を
        コンソールに警告表示する（Phase 5 で Vision フォールバック予定）。
    """
    if pymupdf is None:
        console.print(
            "[red]pymupdf がインストールされていません。"
            "`pip install pymupdf` を実行してください。[/red]"
        )
        return None

    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:  # pragma: no cover
        console.print(f"[red]PDFを開けませんでした: {exc}[/red]")
        return None

    pages: list[str] = []
    scanned_count = 0
    total_pages = doc.page_count

    try:
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            stripped = text.strip()
            if stripped:
                pages.append(f"--- Page {i} ---\n{stripped}")
            if len(stripped) < _SCANNED_PAGE_CHAR_THRESHOLD:
                scanned_count += 1
    finally:
        doc.close()

    if not pages:
        console.print(
            "[yellow]⚠ PDFからテキストを抽出できませんでした"
            "（スキャンPDFの可能性）。Phase 5 で画像OCR対応予定。[/yellow]"
        )
        return None

    combined = "\n\n".join(pages)
    console.print(
        f"[green]✓[/green] PDFから {len(pages)}/{total_pages}ページ, "
        f"{len(combined):,}文字を抽出"
    )

    if total_pages and scanned_count > total_pages / 2:
        console.print(
            f"[yellow]⚠ {scanned_count}/{total_pages} ページでテキスト抽出量が"
            f"少ないため、スキャンPDFの可能性があります。Phase 5 でOCR対応予定。[/yellow]"
        )

    return combined
