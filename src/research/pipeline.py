"""パイプライン層: 入力検証 → Agent呼び出し → レポート保存 → HTML生成."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console

from research.agent_runner import run_agent_sync
from research.config import OUTPUT_DIR, PROJECT_ROOT
from research.job_posting import JobPostingInput, load_job_posting
from research.parsing.markdown_split import split_markdown_and_json
from research.parsing.schema import ReportData
from research.render.html import render_simple_dashboard


@dataclass
class ResearchRequest:
    """CLIからの入力を表す."""

    company: str
    job_posting_paths: list[Path]
    model: str
    skip_detail: bool
    skip_job_fit: bool


@dataclass
class ResearchResult:
    """パイプラインの出力."""

    output_dir: Path
    dashboard_path: Path
    basic_md_path: Path | None
    detail_md_path: Path | None


# Windows で使用できない文字を除去
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1F]')


def _sanitize_dir_name(name: str) -> str:
    """出力ディレクトリ名に使える形へ正規化."""
    normalized = unicodedata.normalize("NFC", name)
    cleaned = _INVALID_CHARS.sub("_", normalized).strip().strip(".")
    return cleaned or "unknown"


def _prepare_output_dir(company: str) -> Path:
    """`output/YYYY-MM-DD_{企業名}/` を作成。衝突時は `_v2`, `_v3` と採番."""
    today = date.today().isoformat()
    base = OUTPUT_DIR / f"{today}_{_sanitize_dir_name(company)}"
    out = base
    n = 2
    while out.exists():
        out = base.with_name(f"{base.name}_v{n}")
        n += 1
    out.mkdir(parents=True, exist_ok=True)
    return out


def run_pipeline(request: ResearchRequest, *, console: Console) -> ResearchResult:
    """パイプラインを実行."""
    # Step 1: 出力ディレクトリ
    output_dir = _prepare_output_dir(request.company)
    console.print(f"出力ディレクトリを作成: [cyan]{output_dir}[/cyan]")

    # Step 2: 求人票ロード（テキスト + 画像）
    job_posting: JobPostingInput | None = None
    if not request.skip_job_fit and request.job_posting_paths:
        job_posting = load_job_posting(
            request.job_posting_paths, output_dir, console
        )
        if job_posting and job_posting.text:
            (output_dir / "job_posting.txt").write_text(
                job_posting.text, encoding="utf-8"
            )
        if job_posting and job_posting.images:
            console.print(
                f"[dim]画像求人票: {len(job_posting.images)}枚を Agent に渡します[/dim]"
            )

    # Step 3: Claude Agent 実行
    #   cwd は PROJECT_ROOT を渡す（.claude/skills を検出させるため）
    console.print()
    agent_results = run_agent_sync(
        request.company,
        job_posting,
        request.model,
        run_basic=True,
        run_detail=not request.skip_detail,
        cwd=str(PROJECT_ROOT),
        console=console,
    )

    # Step 4: Markdownレポートを保存（JSON ブロックは剥がして別途 data.json へ）
    basic_md_path: Path | None = None
    detail_md_path: Path | None = None

    basic_md_body: str | None = None
    detail_md_body: str | None = None
    basic_json: dict | None = None
    detail_json: dict | None = None

    if "basic" in agent_results:
        basic_md_body, basic_json = split_markdown_and_json(
            agent_results["basic"].text
        )
        basic_md_path = output_dir / "report_basic.md"
        basic_md_path.write_text(basic_md_body, encoding="utf-8")
        console.print(f"[green]✓[/green] 基本調査を保存: {basic_md_path.name}")

    if "detail" in agent_results:
        detail_md_body, detail_json = split_markdown_and_json(
            agent_results["detail"].text
        )
        detail_md_path = output_dir / "report_detail.md"
        detail_md_path.write_text(detail_md_body, encoding="utf-8")
        console.print(f"[green]✓[/green] 詳細調査を保存: {detail_md_path.name}")

    # Step 4b: 構造化データを検証して data.json に保存
    report_data: ReportData | None = None
    merged_json: dict | None = basic_json
    if detail_json:
        # 詳細側のフィールドを足し込み（未存在のもののみ優先）
        merged_json = dict(merged_json or {})
        for key, value in detail_json.items():
            if not merged_json.get(key):
                merged_json[key] = value
            elif key == "interview_questions" and isinstance(value, list):
                merged_json[key] = list(merged_json[key]) + list(value)
            elif key == "sources" and isinstance(value, list):
                # URL重複を避けつつマージ
                seen = {s.get("url") for s in merged_json[key] if isinstance(s, dict)}
                for s in value:
                    if isinstance(s, dict) and s.get("url") not in seen:
                        merged_json[key].append(s)

    if merged_json:
        try:
            report_data = ReportData.model_validate(
                {
                    "company": request.company,
                    "surveyed_at": date.today().isoformat(),
                    "model": request.model,
                    **merged_json,
                }
            )
            (output_dir / "data.json").write_text(
                report_data.model_dump_json(indent=2),
                encoding="utf-8",
            )
            console.print(
                f"[green]✓[/green] 構造化データを保存: data.json "
                f"(screening={len(report_data.screening)}, "
                f"sources={len(report_data.sources)}, "
                f"questions={len(report_data.interview_questions)})"
            )
        except ValidationError as e:
            console.print(
                f"[yellow]⚠ 構造化データの検証に失敗: {e.error_count()} 件のエラー[/yellow]"
            )
            console.print(f"[dim]{e}[/dim]")
            report_data = None
    else:
        console.print(
            "[yellow]⚠ JSONブロックが見つかりませんでした。"
            "Markdown からの抽出にフォールバックします。[/yellow]"
        )

    # Step 5: HTMLダッシュボードを生成
    dashboard_path = render_simple_dashboard(
        output_dir=output_dir,
        company=request.company,
        basic_md=basic_md_body,
        detail_md=detail_md_body,
        model=request.model,
        report_data=report_data,
    )
    console.print(f"[green]✓[/green] ダッシュボードを生成: {dashboard_path.name}")

    return ResearchResult(
        output_dir=output_dir,
        dashboard_path=dashboard_path,
        basic_md_path=basic_md_path,
        detail_md_path=detail_md_path,
    )
