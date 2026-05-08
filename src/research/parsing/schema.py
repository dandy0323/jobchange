"""Agent が返すレポート構造化データの pydantic スキーマ.

Phase 2 では基本調査の結果（総合スクリーニング＋出典＋面接質問）のみを扱う。
詳細調査・求人票整合性は Phase 3 以降で拡張予定。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# 総合スクリーニングのバッジ表現
BadgeLiteral = Literal["🟢", "🟡", "🔴", "⚪"]

# 求人票整合性バッジ
JobFitIntegrityLiteral = Literal["✅", "⚠️", "❓"]


class Judgement(BaseModel):
    """総合スクリーニング結果の1行（事業・経済基盤 / 社会的リスク / 社員評価 等）."""

    model_config = ConfigDict(extra="ignore")

    axis: str = Field(description="観点名 (例: '事業・経済基盤')")
    badge: BadgeLiteral = Field(description="判定バッジ (🟢🟡🔴⚪)")
    level_label: str | None = Field(
        default=None,
        description="'懸念なし' 等の人間可読ラベル。未指定なら badge から推定",
    )
    summary: str = Field(description="1〜2文の概要")

    @field_validator("axis", "summary", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("badge", mode="before")
    @classmethod
    def _extract_badge_char(cls, v: object) -> object:
        """'🟢 懸念なし' のように前後に文字があっても絵文字を拾う."""
        if isinstance(v, str):
            for ch in v:
                if ch in ("🟢", "🟡", "🔴", "⚪"):
                    return ch
        return v


class Source(BaseModel):
    """出典1件."""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(ge=1, description="1始まりの連番")
    title: str
    url: str  # HttpUrl だと日本語URLで落ちる可能性があるため緩い str
    fetched_at: date | None = None

    @field_validator("title", "url", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v


class InterviewQuestion(BaseModel):
    """面接で聞くべき質問."""

    model_config = ConfigDict(extra="ignore")

    category: str = Field(description="カテゴリ (例: '事業戦略', 'カルチャー')")
    question: str
    rationale: str | None = None


class JobFitRow(BaseModel):
    """求人票の記載と調査実態の1行比較."""

    model_config = ConfigDict(extra="ignore")

    claim: str = Field(description="求人票の記載内容（要約）")
    finding: str = Field(description="Web調査で確認できた実態")
    integrity: JobFitIntegrityLiteral = Field(description="整合性 (✅/⚠️/❓)")
    note: str | None = Field(default=None, description="任意の備考")

    @field_validator("claim", "finding", mode="before")
    @classmethod
    def _strip_text(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("integrity", mode="before")
    @classmethod
    def _extract_integrity_char(cls, v: object) -> object:
        """'⚠️ 差異あり' のように前後文字があっても絵文字だけ拾う."""
        if isinstance(v, str):
            # ⚠️ は U+26A0 + U+FE0F の2コードポイント。2文字単位で先にチェック
            if "⚠️" in v:
                return "⚠️"
            for ch in v:
                if ch in ("✅", "❓"):
                    return ch
        return v


class ReportData(BaseModel):
    """Agent から得た構造化レポートデータ全体."""

    model_config = ConfigDict(extra="ignore")

    company: str
    surveyed_at: date | None = None
    model: str | None = None

    screening: list[Judgement] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    interview_questions: list[InterviewQuestion] = Field(default_factory=list)
    additional_notes: list[str] = Field(default_factory=list)

    # Phase 4: 求人票整合性
    job_fit: list[JobFitRow] = Field(default_factory=list)
    additional_considerations: list[str] = Field(
        default_factory=list,
        description="求人票には書かれていないが面接で確認すべき追加事項",
    )
