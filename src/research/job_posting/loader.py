"""拡張子に応じて求人票ファイルを適切なパーサへルーティング."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from research.job_posting.image_parser import NormalizedImage, normalize_image
from research.job_posting.pdf_parser import extract_pdf_text


# 対応フォーマット
_TEXT_EXTS = {".txt", ".md"}
_PDF_EXTS = {".pdf"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".heic"}


@dataclass
class JobPostingInput:
    """求人票の入力情報（テキスト or 画像パス群）.

    - `text`: PDFやテキストファイルから抽出した本文。画像のみの場合は None。
    - `images`: Vision 入力用に正規化した画像ファイル群（通常 `output_dir / "job_posting"` 配下）。
    - `source_names`: ユーザーが指定した元ファイル名（表示用）。

    agent_runner は `text` があればプロンプト埋め込み、
    `images` があれば Agent に画像パスを渡してRead+Visionで解析させる。
    """

    text: str | None = None
    images: list[NormalizedImage] = field(default_factory=list)
    source_names: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.text and not self.images

    @property
    def has_image(self) -> bool:
        return bool(self.images)


def load_job_posting(
    paths: list[Path],
    output_dir: Path,
    console: Console,
) -> JobPostingInput | None:
    """1つ以上の求人票ファイルをロード.

    - `.pdf` : pymupdf で抽出（スキャンPDFは画像化フォールバック予定）
    - `.txt` / `.md` : そのまま読み込み
    - `.png` / `.jpg` / `.jpeg` / `.heic` : Vision 入力用に正規化して画像として保持

    複数ファイルを渡した場合、テキストは連結、画像は配列に追加される。
    失敗した場合でも、他のファイルの成功結果は保持する（ベストエフォート）。
    """
    if not paths:
        return None

    result = JobPostingInput()
    image_dir = output_dir / "job_posting_images"
    text_fragments: list[str] = []
    image_idx = 1

    for path in paths:
        if not path.exists():
            console.print(f"[red]求人票ファイルが見つかりません: {path}[/red]")
            continue

        ext = path.suffix.lower()
        result.source_names.append(path.name)

        if ext in _PDF_EXTS:
            extracted = extract_pdf_text(path, console)
            if extracted:
                text_fragments.append(f"# {path.name}\n\n{extracted}")
            continue

        if ext in _TEXT_EXTS:
            try:
                raw = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                raw = path.read_text(encoding="cp932", errors="replace")
            text_fragments.append(f"# {path.name}\n\n{raw}")
            continue

        if ext in _IMAGE_EXTS:
            normalized = normalize_image(
                path, image_dir, console, index=image_idx
            )
            if normalized:
                result.images.append(normalized)
                image_idx += 1
            continue

        console.print(
            f"[yellow]⚠ 対応していない求人票フォーマット: {ext}。スキップします。[/yellow]"
        )

    if text_fragments:
        result.text = "\n\n---\n\n".join(text_fragments)

    if result.is_empty:
        return None

    return result
