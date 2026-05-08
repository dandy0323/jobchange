"""typer-based CLI."""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console

from research import __version__
from research.config import DEFAULT_MODEL, PROJECT_ROOT, resolve_model
from research.pipeline import ResearchRequest, run_pipeline


def _load_env_robust() -> None:
    """`.env` を BOM 耐性付きで読み込み、主要キーの欠落を警告.

    - UTF-8 BOM が付いた .env を dotenv が `\\ufeffANTHROPIC_API_KEY` として
      誤解釈する問題があるため、事前にBOMを除去してからロードする。
    - 環境変数が既に設定されている場合は尊重するため override=False。
    """
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        try:
            raw = env_path.read_bytes()
            if raw.startswith(b"\xef\xbb\xbf"):
                env_path.write_bytes(raw[3:])
                console.print(
                    "[yellow]⚠ .env ファイルに UTF-8 BOM が含まれていたため除去しました。[/yellow]"
                )
        except OSError as exc:
            console.print(f"[yellow]⚠ .env の前処理でエラー ({exc})[/yellow]")

    # 既存のシェル環境変数が空文字列だと load_dotenv(override=False) で
    # 上書きされずに「未設定」になる事故がある（Claude Code 配下起動など）。
    # .env が存在するなら優先的に反映させる。
    existing = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    use_override = env_path.exists() and not existing
    load_dotenv(
        str(env_path) if env_path.exists() else None,
        override=use_override,
    )

    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        console.print(
            "[red]✗ ANTHROPIC_API_KEY が設定されていません。"
            ".env ファイル、または環境変数を確認してください。[/red]"
        )
    elif not key.startswith("sk-ant"):
        console.print(
            "[yellow]⚠ ANTHROPIC_API_KEY の形式が想定と異なります "
            f"(prefix: {key[:8]}…)[/yellow]"
        )

app = typer.Typer(
    name="company-research",
    help="企業名を入力すると、公開情報から調査レポート + ダッシュボード型HTMLを自動生成します。",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()


def _open_in_default_browser(path: Path) -> None:
    """OS既定の関連付けでHTMLファイルを開く.

    - Windows: `os.startfile` で拡張子関連付け → 既定ブラウザ（Brave等）で開く
      `webbrowser.open()` は file:// を Edge のプロトコルハンドラ経由で開くことがあり、
      MSN ニュースへフォールバックする事象が報告されているため避ける。
    - macOS: `open`
    - Linux: `xdg-open`
    失敗時は従来の webbrowser にフォールバック。
    """
    resolved = path.resolve()
    console.print(f"ブラウザで開いています: [dim]{resolved}[/dim]")
    try:
        if sys.platform == "win32":
            os.startfile(str(resolved))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(resolved)])
            return
        # Linux / その他 Unix
        subprocess.Popen(["xdg-open", str(resolved)])
        return
    except Exception as exc:  # pragma: no cover
        console.print(
            f"[yellow]⚠ OS既定の方法で開けませんでした ({exc})。"
            "webbrowser にフォールバックします。[/yellow]"
        )
        webbrowser.open(resolved.as_uri())


@app.command()
def research(
    company: str = typer.Option(
        ...,
        "--company",
        "-c",
        help="調査対象の企業名（例: '株式会社スペースシャワーネットワーク'）",
    ),
    job_posting: list[Path] = typer.Option(
        [],
        "--job-posting",
        "-j",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="求人票ファイル（PDF/HEIC/PNG/JPG対応）。複数指定可。任意。",
    ),
    model: str = typer.Option(
        DEFAULT_MODEL,
        "--model",
        "-m",
        help="使用するClaudeモデル。'sonnet'/'opus'/'haiku' エイリアスも可。",
    ),
    skip_detail: bool = typer.Option(
        False,
        "--skip-detail",
        help="詳細調査をスキップし、基本調査のみ実行します。",
    ),
    skip_job_fit: bool = typer.Option(
        False,
        "--skip-job-fit",
        help="求人票との整合性チェックをスキップします。",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="完了後にブラウザで自動的にダッシュボードを開きません。",
    ),
) -> None:
    """企業調査を実行し、ダッシュボードHTMLを生成します。"""
    _load_env_robust()

    resolved_model = resolve_model(model)
    console.rule(f"[bold cyan]企業調査: {company}")
    console.print(f"モデル: [yellow]{resolved_model}[/yellow]")
    if job_posting:
        console.print(f"求人票: [yellow]{', '.join(str(p) for p in job_posting)}[/yellow]")
    console.print(
        f"スキップ: 詳細={skip_detail} / 求人票整合性={skip_job_fit}",
        style="dim",
    )
    console.print()

    request = ResearchRequest(
        company=company,
        job_posting_paths=list(job_posting),
        model=resolved_model,
        skip_detail=skip_detail,
        skip_job_fit=skip_job_fit,
    )

    try:
        result = run_pipeline(request, console=console)
    except KeyboardInterrupt:
        console.print("\n[yellow]ユーザーにより中断されました。[/yellow]")
        raise typer.Exit(code=130)
    except Exception as exc:
        console.print(f"[red]エラー: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print()
    console.rule("[bold green]完了")
    console.print(f"出力ディレクトリ: [cyan]{result.output_dir}[/cyan]")
    console.print(f"ダッシュボード: [cyan]{result.dashboard_path}[/cyan]")

    if not no_open:
        _open_in_default_browser(result.dashboard_path)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="バインドするホスト"),
    port: int = typer.Option(8765, "--port", "-p", help="待ち受けるポート番号"),
    no_open: bool = typer.Option(False, "--no-open", help="ブラウザを自動で開かない"),
) -> None:
    """Web UIサーバーを起動します（求人票アップロード + ダッシュボード閲覧）。"""
    _load_env_robust()
    from research.server import run_server

    url = f"http://{host}:{port}"
    console.print(f"[bold cyan]Web UIサーバーを起動: {url}[/bold cyan]")
    console.print("停止するには Ctrl+C を押してください。")

    if not no_open:
        import threading, time

        def _delayed_open():
            time.sleep(1.5)
            try:
                if sys.platform == "win32":
                    os.startfile(url)
                else:
                    import webbrowser
                    webbrowser.open(url)
            except Exception:
                pass

        threading.Thread(target=_delayed_open, daemon=True).start()

    run_server(host=host, port=port)


@app.command()
def version() -> None:
    """バージョンを表示します。"""
    console.print(f"company-research v{__version__}")


def main() -> None:
    """エントリポイント."""
    try:
        app()
    except SystemExit:
        raise
    except Exception as exc:
        console.print(f"[red]未ハンドルエラー: {exc}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
