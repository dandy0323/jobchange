"""Claude Agent SDK の呼び出し層.

Phase 1 では基本調査のみを実行する素朴な実装。
`setting_sources=["project"]` で `.claude/skills/` が自動ロードされる前提。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console

try:
    from claude_agent_sdk import (  # type: ignore
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        ResultMessage,
        TextBlock,
    )
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "claude-agent-sdk がインストールされていません。"
        "`pip install claude-agent-sdk` もしくは `pip install -e .` を実行してください。"
    ) from e

from research.config import PROJECT_ROOT
from research.job_posting import JobPostingInput


def _load_extension_prompt() -> str | None:
    """`prompts/basic_extension.md` を読み込んで返す。存在しなければ None."""
    path: Path = PROJECT_ROOT / "prompts" / "basic_extension.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except FileNotFoundError:
        return None


def _load_job_fit_addendum() -> str | None:
    """求人票整合性チェック用の追加指示を読み込む."""
    path: Path = PROJECT_ROOT / "prompts" / "job_fit_addendum.md"
    try:
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    except FileNotFoundError:
        return None


@dataclass
class AgentResult:
    """Claudeからの応答結果."""

    text: str
    turns: int
    total_cost_usd: float | None = None


def _build_basic_prompt(company: str, job_posting: JobPostingInput | None) -> str:
    """基本調査の指示プロンプトを構築."""
    lines = [
        f"以下の企業について「企業調査-基本」Skillを使って調査してください。",
        "",
        f"- 企業名: {company}",
    ]
    if job_posting and job_posting.text:
        lines.extend(
            [
                "",
                "以下の求人票情報も参考にしてください:",
                "```",
                job_posting.text[:6000],  # トークン削減のため6000文字に制限
                "```",
            ]
        )
    if job_posting and job_posting.images:
        # 画像はまだここでは詳細使用しない（基本調査では参考情報として案内のみ）
        image_list = "\n".join(
            f"- {img.path.as_posix()} （元ファイル: {img.original_name}）"
            for img in job_posting.images
        )
        lines.extend(
            [
                "",
                "求人票は画像でも提供されています（詳細調査時にRead toolで読み込んでください）:",
                image_list,
            ]
        )
    lines.extend(
        [
            "",
            "実行手順:",
            "1. Skill の手順に従ってWeb検索で情報収集",
            "2. Markdownレポートを作業ディレクトリに保存",
            "3. 応答の末尾にレポート本文を出力してください",
            "",
            "【重要な追加指示 — 社員評価の重視】",
            "「■ 総合スクリーニング結果」の表には、Skillで指定されている",
            "「事業・経済基盤」「社会的リスク」の2行に加えて、",
            "3行目として必ず「社員評価」の行を追加してください。",
            "",
            "- 判定は OpenWork / キャリコネ / 転職会議 / ライトハウス 等の",
            "  社員口コミサイトの評価スコアと定性コメントから総合的に判断し、",
            "  🟢（肯定的評価が多数）/ 🟡（賛否両論・要確認）/ 🔴（懸念点が多数）/ ⚪（情報なし）",
            "  の4段階で示してください。",
            "- 概要欄には、判定の根拠となる評点（例: OpenWork総合スコア、残業時間、",
            "  有給取得率など）と印象的な定性コメントのエッセンスを1〜2文で記載してください。",
            "",
            "また本文の 5-3「顧客からの評判」セクションには、",
            "必ず「社員評価」の小見出しを設け、【良い点】【懸念点】の2つの箇条書き形式で",
            "口コミの具体的内容を整理してください。出典URLも明記してください。",
        ]
    )
    return "\n".join(lines)


def _build_detail_prompt(company: str, job_posting: JobPostingInput | None) -> str:
    """詳細調査の指示プロンプトを構築."""
    lines = [
        f"続いて、{company} について「企業調査-詳細」Skillを使って調査してください。",
        "",
        "基本調査の結果を踏まえ、組織・カルチャー、職務・スキル、労働条件の3観点を深掘りしてください。",
    ]
    has_any_posting = job_posting is not None and not job_posting.is_empty
    if has_any_posting:
        lines.extend(
            [
                "",
                "求人票との整合性チェックセクションも必ず含めてください。",
            ]
        )
        if job_posting.text:
            lines.extend(
                [
                    "",
                    "【求人票テキスト】",
                    "```",
                    job_posting.text[:6000],
                    "```",
                ]
            )
        if job_posting.images:
            image_list = "\n".join(
                f"- {img.path.as_posix()} （{img.mime}, 元: {img.original_name}）"
                for img in job_posting.images
            )
            lines.extend(
                [
                    "",
                    "【求人票画像】 以下のファイルを Read tool で開き、画像内の",
                    "テキスト・項目を正確に読み取ってから整合性チェックに使用してください。",
                    image_list,
                ]
            )
        # 求人票がある場合は addendum を本文末尾にぶら下げる
        addendum = _load_job_fit_addendum()
        if addendum:
            lines.extend(["", "---", "", addendum])
    lines.extend(
        [
            "",
            "【重要 — 構造化データの再出力】",
            "system prompt の追加ルールに従い、今回も応答の末尾に必ず JSON ブロックを",
            "1つ出力してください。特に以下を厳守してください:",
            "",
            "1. `interview_questions` には詳細調査の内容を踏まえた質問を **5〜10件** 収録。",
            "   カテゴリは「組織・カルチャー」「職務・スキル」「労働条件」等、詳細調査の3観点を",
            "   バランスよく含める。",
            "2. `sources` は詳細調査で追加した出典を網羅し、id は 1 から通し番号で振り直す",
            "   （基本調査の出典と重複するURLは1件にまとめる）。",
            "3. `screening` は基本調査と同じ3観点（事業・経済基盤 / 社会的リスク / 社員評価）を",
            "   変更なく出力してよい。",
            "",
            "JSONブロック以降に文章を書かないでください。",
        ]
    )
    return "\n".join(lines)


async def _run_query(client: ClaudeSDKClient, prompt: str, console: Console) -> AgentResult:
    """クエリを1本実行し、アシスタント応答を収集."""
    await client.query(prompt)

    collected: list[str] = []
    turns = 0
    cost: float | None = None

    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    collected.append(block.text)
                    # ストリーミング時の進捗表示（冒頭40文字）
                    preview = block.text.strip().replace("\n", " ")[:40]
                    if preview:
                        console.print(f"[dim]… {preview}…[/dim]")
        elif isinstance(message, ResultMessage):
            turns = getattr(message, "num_turns", 0) or 0
            cost = getattr(message, "total_cost_usd", None)

    full_text = "\n".join(collected)

    # API 認証エラーなどの致命的な失敗を検出して即座に例外化
    # （1つ目のクエリが失敗したまま2つ目が走って二重請求&待ち時間の無駄を防ぐ）
    _raise_if_api_error(full_text)

    return AgentResult(text=full_text, turns=turns, total_cost_usd=cost)


_API_ERROR_PATTERNS = (
    # 認証エラー
    "Failed to authenticate",
    "authentication_error",
    "Invalid authentication credentials",
    # 課金・クレジット不足
    "Credit balance is too low",
    "credit_balance",
    "billing_error",
    "insufficient_quota",
    # 一般的なAPIエラー
    "invalid_request_error",
    "permission_error",
    "rate_limit_error",
    "overloaded_error",
    "api_error",
)


def _raise_if_api_error(text: str) -> None:
    """応答本文が Anthropic API のエラーレスポンスそのままなら RuntimeError を投げる.

    検出ロジック:
    1. 既知のエラーパターンのいずれかを含む
    2. 応答が極端に短く (100文字未満) Markdown構造を含まない
       → 「Credit balance is too low」のような短いエラーメッセージを拾う
    """
    head = text.strip()[:600]
    if not head:
        return
    # 既知のエラー文字列パターン
    for pat in _API_ERROR_PATTERNS:
        if pat in head:
            raise RuntimeError(
                f"Claude API からエラーレスポンスを受け取りました: {head[:300]}"
            )
    # Markdownレポートは通常「#」見出しや表を含む。100文字未満で見出しがなければ異常。
    if len(head) < 100 and "#" not in head and "|" not in head:
        raise RuntimeError(
            f"Claude Agent から予期せぬ短い応答を受け取りました: {head!r}"
        )


async def run_agent(
    company: str,
    job_posting: JobPostingInput | None,
    model: str,
    *,
    run_basic: bool,
    run_detail: bool,
    cwd: str,
    console: Console,
) -> dict[str, AgentResult]:
    """基本・詳細調査を順に実行して結果を返す.

    Returns:
        {"basic": AgentResult, "detail": AgentResult} の部分的な辞書。
    """
    extension_prompt = _load_extension_prompt()
    if extension_prompt:
        console.print(
            "[dim]● append_system_prompt: prompts/basic_extension.md を注入[/dim]"
        )

    options_kwargs: dict = {
        "setting_sources": ["project"],  # .claude/skills を自動ロード
        "allowed_tools": ["WebSearch", "WebFetch", "Write", "Read", "Glob", "Grep"],
        "permission_mode": "bypassPermissions",
        "model": model,
        "cwd": cwd,
    }
    if extension_prompt:
        # Claude Code のデフォルト system prompt を維持しつつ、追加指示を末尾へ
        options_kwargs["system_prompt"] = {
            "type": "preset",
            "preset": "claude_code",
            "append": extension_prompt,
        }

    options = ClaudeAgentOptions(**options_kwargs)

    results: dict[str, AgentResult] = {}
    async with ClaudeSDKClient(options=options) as client:
        if run_basic:
            console.print("[bold]▶ 基本調査を実行中...[/bold]")
            results["basic"] = await _run_query(
                client, _build_basic_prompt(company, job_posting), console
            )
            console.print(
                f"[green]✓ 基本調査完了[/green] "
                f"(turns={results['basic'].turns}, "
                f"cost=${results['basic'].total_cost_usd or 0:.4f})"
            )

        if run_detail:
            console.print("[bold]▶ 詳細調査を実行中...[/bold]")
            results["detail"] = await _run_query(
                client, _build_detail_prompt(company, job_posting), console
            )
            console.print(
                f"[green]✓ 詳細調査完了[/green] "
                f"(turns={results['detail'].turns}, "
                f"cost=${results['detail'].total_cost_usd or 0:.4f})"
            )

    return results


def run_agent_sync(*args, **kwargs) -> dict[str, AgentResult]:
    """同期ラッパー."""
    return asyncio.run(run_agent(*args, **kwargs))
