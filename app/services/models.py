from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


Severity = Literal["critical", "high", "medium", "low"]


class ReviewIssue(BaseModel):
    title: str
    severity: Severity = "medium"
    category: str = "general"
    file: str = "repository-wide"
    line: int | None = None
    suggestion: str
    rationale: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source_model: str = "static"


class ModelReview(BaseModel):
    model_name: str
    family: str
    enabled: bool
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[ReviewIssue] = Field(default_factory=list)
    risk_score: int = Field(default=50, ge=0, le=100)
    raw_response: str | None = None
    error: str | None = None


class RepoSnapshot(BaseModel):
    repo_name: str
    branch: str
    commit: str
    file_summaries: list[dict]
    stats: dict


class ReviewReport(BaseModel):
    repository: str
    branch: str
    commit: str
    executive_summary: str
    overall_risk_score: int
    strengths: list[str]
    key_findings: list[ReviewIssue]
    model_reviews: list[ModelReview]
    coverage: dict
    quick_wins: list[str]
    markdown_report: str
