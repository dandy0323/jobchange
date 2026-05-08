"""FastAPI Webサーバ: 求人票アップロード + 調査実行 + ダッシュボード閲覧.

フロー:
    GET /                         → index.html (企業名 + ファイルD&Dアップロード)
    POST /jobs                    → 調査ジョブ作成 → job_id を返す
    GET /jobs/{job_id}/status     → 進捗 & 完了時の dashboard_url を返す
    GET /jobs/{job_id}/logs       → 簡易ログ
    GET /outputs/{dir}/...        → output/ 配下を静的配信（ダッシュボード閲覧）

実行:
    python -m research.cli serve --host 127.0.0.1 --port 8765
"""

from __future__ import annotations

import shutil
import threading
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich.console import Console

from research.config import OUTPUT_DIR, PROJECT_ROOT, resolve_model
from research.pipeline import ResearchRequest, run_pipeline


# ─────────────────────────────────────────────────────────────
# ジョブ管理
# ─────────────────────────────────────────────────────────────

_UPLOAD_DIR = PROJECT_ROOT / "uploads"
_UPLOAD_DIR.mkdir(exist_ok=True)


@dataclass
class JobState:
    """進行中/完了済みジョブのメモリ上状態."""

    job_id: str
    company: str
    model: str
    skip_detail: bool
    skip_job_fit: bool
    upload_paths: list[Path] = field(default_factory=list)
    status: str = "queued"        # queued | running | succeeded | failed
    logs: list[str] = field(default_factory=list)
    dashboard_url: str | None = None
    output_dir: Path | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime | None = None


class _LogCapture:
    """Rich Console の `file` に差し込む file-like object.

    write された内容を改行単位で JobState.logs へ転送する。
    Console をサブクラス化するアプローチは `_buffer` 属性と衝突するため不可。
    """

    def __init__(self, job: JobState) -> None:
        self._job = job
        self._pending = ""

    def write(self, data: str) -> int:
        if not data:
            return 0
        self._pending += data
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            stripped = line.rstrip()
            if stripped:
                self._job.logs.append(stripped)
        return len(data)

    def flush(self) -> None:
        if self._pending.strip():
            self._job.logs.append(self._pending.rstrip())
        self._pending = ""

    def isatty(self) -> bool:
        return False


def _make_job_console(job: JobState) -> Console:
    """JobState のログを拾う Console を生成."""
    return Console(
        file=_LogCapture(job),
        force_terminal=False,
        color_system=None,
        width=120,
        soft_wrap=False,
        highlight=False,
    )


_jobs: dict[str, JobState] = {}
_jobs_lock = threading.Lock()


def _run_job(job: JobState) -> None:
    """別スレッドで run_pipeline を実行."""
    # NOTE: Console 初期化も try の中に入れる（初期化失敗時も status=failed にする）
    try:
        job.status = "running"
        console = _make_job_console(job)
        request = ResearchRequest(
            company=job.company,
            job_posting_paths=job.upload_paths,
            model=job.model,
            skip_detail=job.skip_detail,
            skip_job_fit=job.skip_job_fit,
        )
        result = run_pipeline(request, console=console)
        job.output_dir = result.output_dir
        # dashboard は /outputs/{dir}/dashboard.html で配信
        try:
            rel = result.dashboard_path.relative_to(OUTPUT_DIR)
        except ValueError:
            rel = Path(result.dashboard_path.name)
        job.dashboard_url = "/outputs/" + rel.as_posix()
        job.status = "succeeded"
    except Exception as exc:
        job.status = "failed"
        job.error = f"{type(exc).__name__}: {exc}"
        job.logs.append(f"[error] {job.error}")
        job.logs.append(traceback.format_exc())
    finally:
        job.finished_at = datetime.utcnow()


# ─────────────────────────────────────────────────────────────
# FastAPIアプリ
# ─────────────────────────────────────────────────────────────

TEMPLATES_DIR = PROJECT_ROOT / "templates"
_jinja = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR / "server")),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _render(template_name: str, **context: Any) -> str:
    template = _jinja.get_template(template_name)
    return template.render(**context)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # 起動時: output ディレクトリを確実に存在させる
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="企業調査ダッシュボード",
    version="0.1.0",
    lifespan=_lifespan,
)

# 静的配信（ダッシュボード資産を含む）
app.mount(
    "/outputs",
    StaticFiles(directory=str(OUTPUT_DIR), html=True),
    name="outputs",
)
app.mount(
    "/assets",
    StaticFiles(directory=str(TEMPLATES_DIR / "assets")),
    name="assets",
)


# ─────────────────────────────────────────────────────────────
# ルート
# ─────────────────────────────────────────────────────────────

_ALLOWED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".txt", ".md"}


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    # 既存の output/ の一覧を渡して最近の調査を表示
    recent = []
    if OUTPUT_DIR.exists():
        for d in sorted(
            OUTPUT_DIR.iterdir(), key=lambda p: p.name, reverse=True
        ):
            if not d.is_dir():
                continue
            dashboard = d / "dashboard.html"
            if not dashboard.exists():
                continue
            # 企業名は ディレクトリ名の先頭日付を除いた部分
            name = d.name
            parts = name.split("_", 1)
            display = parts[1] if len(parts) == 2 else name
            recent.append(
                {
                    "display": display,
                    "date": parts[0] if len(parts) == 2 else "",
                    "url": f"/outputs/{d.name}/dashboard.html",
                    "dir": d.name,
                }
            )
            if len(recent) >= 20:
                break

    return HTMLResponse(_render("index.html.j2", recent=recent))


@app.post("/jobs")
async def create_job(
    request: Request,
    company: str = Form(...),
    model: str = Form("sonnet"),
    skip_detail: bool = Form(False),
    skip_job_fit: bool = Form(False),
) -> JSONResponse:
    """調査ジョブを作成し、job_id を返す."""
    form = await request.form()
    company = (company or "").strip()
    if not company:
        raise HTTPException(status_code=400, detail="企業名が未入力です")

    job_id = uuid.uuid4().hex[:10]
    job_dir = _UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # アップロードファイルを保存
    upload_paths: list[Path] = []
    for key, value in form.multi_items():
        if key != "files":
            continue
        if not isinstance(value, UploadFile):
            continue
        if not value.filename:
            continue
        ext = Path(value.filename).suffix.lower()
        if ext not in _ALLOWED_EXTS:
            continue
        target = job_dir / value.filename
        with target.open("wb") as f:
            shutil.copyfileobj(value.file, f)
        upload_paths.append(target)

    resolved_model = resolve_model(model)
    job = JobState(
        job_id=job_id,
        company=company,
        model=resolved_model,
        skip_detail=bool(skip_detail),
        skip_job_fit=bool(skip_job_fit) or not upload_paths,
        upload_paths=upload_paths,
    )
    with _jobs_lock:
        _jobs[job_id] = job

    # 別スレッドで実行（blocking な run_pipeline のため）
    thread = threading.Thread(target=_run_job, args=(job,), daemon=True)
    thread.start()

    return JSONResponse(
        {
            "job_id": job_id,
            "status": job.status,
            "status_url": f"/jobs/{job_id}/status",
            "stream_url": f"/jobs/{job_id}",
        }
    )


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(job_id: str) -> HTMLResponse:
    """進捗表示ページ（ポーリングで状態を確認）."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return HTMLResponse(_render("progress.html.j2", job=job))


@app.get("/jobs/{job_id}/status")
async def job_status(job_id: str) -> JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(
        {
            "job_id": job.job_id,
            "company": job.company,
            "status": job.status,
            "dashboard_url": job.dashboard_url,
            "error": job.error,
            "recent_logs": job.logs[-30:],  # 末尾だけ
            "log_count": len(job.logs),
            "created_at": job.created_at.isoformat(),
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
    )


@app.get("/jobs/{job_id}/logs")
async def job_logs(job_id: str, since: int = 0) -> JSONResponse:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JSONResponse(
        {
            "job_id": job.job_id,
            "status": job.status,
            "logs": job.logs[since:],
            "next_since": len(job.logs),
        }
    )


# ─────────────────────────────────────────────────────────────
# uvicorn 起動
# ─────────────────────────────────────────────────────────────


def run_server(host: str = "127.0.0.1", port: int = 8765, reload: bool = False) -> None:
    import uvicorn

    uvicorn.run(
        "research.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
