"""画像ファイル (PNG/JPG/HEIC) をVision投入用に正規化するパーサー.

方針:
- HEIC は Claude の直接添付がサポートされない/不安定なので、常に PNG へ変換してから渡す。
- PNG/JPG はサイズが極端に大きい場合のみ長辺 2000px 以下にリサイズ（Visionトークン節約）。
- 画像中身のOCRは LLM (Claude Agent) 側に任せる。本モジュールはファイル正規化のみ。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

try:
    from PIL import Image  # type: ignore
except ImportError:  # pragma: no cover
    Image = None  # type: ignore

try:
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    _HEIF_OK = True
except ImportError:  # pragma: no cover
    _HEIF_OK = False


# Vision 入力の長辺上限（ピクセル）— トークンコスト抑制目的
_MAX_LONG_EDGE = 2000
# JPEGエンコーディング品質
_JPEG_QUALITY = 85


@dataclass
class NormalizedImage:
    """正規化された画像ファイルの情報."""

    path: Path          # 実際に LLM へ渡すファイル（多くは output_dir に書き出したもの）
    original_name: str  # 元のファイル名（表示用）
    mime: str           # "image/png" / "image/jpeg"


def normalize_image(
    src: Path,
    dest_dir: Path,
    console: Console,
    *,
    index: int = 1,
) -> NormalizedImage | None:
    """画像ファイルを LLM に渡せる形へ正規化して `dest_dir` に保存.

    Args:
        src: 入力画像ファイル（.png / .jpg / .jpeg / .heic）
        dest_dir: 変換後ファイルの出力先（通常は求人票専用ディレクトリ）
        console: rich Console
        index: 複数枚対応のための連番（ファイル名に付与）

    Returns:
        NormalizedImage / 失敗時は None
    """
    if Image is None:
        console.print(
            "[red]Pillow がインストールされていません。"
            "`pip install pillow pillow-heif` を実行してください。[/red]"
        )
        return None

    ext = src.suffix.lower()
    if ext == ".heic" and not _HEIF_OK:
        console.print(
            "[red]pillow-heif が読み込めませんでした。"
            "`pip install pillow-heif` を実行してください。[/red]"
        )
        return None

    try:
        img = Image.open(src)
    except Exception as exc:  # pragma: no cover
        console.print(f"[red]画像を開けませんでした ({src.name}): {exc}[/red]")
        return None

    # 透過/カラーモード補正（HEIC→PNG 時の安全側対応）
    if img.mode not in ("RGB", "RGBA", "L"):
        img = img.convert("RGB")

    # 長辺 2000px 超ならリサイズ
    w, h = img.size
    long_edge = max(w, h)
    if long_edge > _MAX_LONG_EDGE:
        scale = _MAX_LONG_EDGE / long_edge
        new_size = (int(w * scale), int(h * scale))
        img = img.resize(new_size, Image.LANCZOS)
        console.print(
            f"[dim]画像リサイズ: {w}x{h} → {new_size[0]}x{new_size[1]} (長辺 {_MAX_LONG_EDGE}px)[/dim]"
        )

    dest_dir.mkdir(parents=True, exist_ok=True)

    # HEIC は PNG で保存、それ以外は元形式を維持（JPEG は JPEG で）
    if ext == ".heic":
        out_path = dest_dir / f"job_posting_{index:02d}.png"
        # PNG は透過保持のため RGBA→RGB 変換はしない
        img.save(out_path, "PNG", optimize=True)
        mime = "image/png"
        console.print(
            f"[green]✓[/green] HEIC→PNG 変換: {src.name} → {out_path.name}"
        )
    elif ext in (".jpg", ".jpeg"):
        out_path = dest_dir / f"job_posting_{index:02d}.jpg"
        # JPEGはアルファ非対応なので RGB に落とす
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out_path, "JPEG", quality=_JPEG_QUALITY, optimize=True)
        mime = "image/jpeg"
        console.print(f"[green]✓[/green] JPEG保存: {src.name} → {out_path.name}")
    else:  # .png など
        out_path = dest_dir / f"job_posting_{index:02d}.png"
        img.save(out_path, "PNG", optimize=True)
        mime = "image/png"
        console.print(f"[green]✓[/green] PNG保存: {src.name} → {out_path.name}")

    return NormalizedImage(path=out_path, original_name=src.name, mime=mime)
