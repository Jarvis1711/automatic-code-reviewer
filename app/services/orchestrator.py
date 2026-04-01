from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Callable, Awaitable

from .analyzers import run_static_analysis
from .models import ModelReview, RepoSnapshot, ReviewIssue, ReviewReport
from .providers import get_default_providers
from .report import build_markdown_report


def _normalize_key(issue: ReviewIssue) -> str:
    return f"{issue.file.lower()}|{issue.category.lower()}|{issue.title.lower()}"


def _merge_issues(reviews: list[ModelReview]) -> list[ReviewIssue]:
    merged: dict[str, ReviewIssue] = {}
    votes: defaultdict[str, int] = defaultdict(int)

    for review in reviews:
        for issue in review.issues:
            key = _normalize_key(issue)
            votes[key] += 1
            if key not in merged:
                merged[key] = issue
                continue

            existing = merged[key]
            if issue.confidence > existing.confidence:
                merged[key] = issue

    ordered = sorted(
        merged.items(),
        key=lambda item: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(item[1].severity, 4),
            -votes[item[0]],
            -item[1].confidence,
        ),
    )
    return [issue for _, issue in ordered]


def _compute_quick_wins(issues: list[ReviewIssue]) -> list[str]:
    wins: list[str] = []
    if any(i.category == "security" for i in issues):
        wins.append("Rotate and externalize any detected credentials using environment variables and a secret manager.")
    if any(i.category in {"maintainability", "readability"} for i in issues):
        wins.append("Create a short debt burn-down for TODO/FIXME/HACK markers and enforce ownership in backlog grooming.")
    if any(i.severity in {"critical", "high"} for i in issues):
        wins.append("Prioritize critical/high findings first and add CI gates to block regressions on these categories.")
    return wins[:5]


def _build_executive_summary(snapshot: RepoSnapshot, issues: list[ReviewIssue], score: int) -> str:
    critical = sum(1 for i in issues if i.severity == "critical")
    high = sum(1 for i in issues if i.severity == "high")
    return (
        f"Multi-model review analyzed {snapshot.stats['total_files_analyzed']} files across "
        f"{len(snapshot.stats.get('languages', {}))} languages. "
        f"Overall risk is assessed at {score}/100 with {critical} critical and {high} high-severity findings. "
        "Consensus issues represent concerns surfaced by at least one review engine and prioritized by severity and confidence."
    )


async def generate_review_report(snapshot: RepoSnapshot) -> ReviewReport:
    static_review = run_static_analysis(snapshot.file_summaries)
    providers = get_default_providers()

    repo_context = {
        "repo_name": snapshot.repo_name,
        "branch": snapshot.branch,
        "commit": snapshot.commit,
        "stats": snapshot.stats,
        "files": [
            {
                "path": f["path"],
                "language": f["language"],
                "size_chars": f["size_chars"],
                "line_count": f["line_count"],
                "content": f["content"],
            }
            for f in snapshot.file_summaries
        ],
    }

    tasks = [provider.review(repo_context) for provider in providers]
    llm_reviews = await asyncio.gather(*tasks)
    all_reviews: list[ModelReview] = [static_review, *llm_reviews]

    return _build_final_report(snapshot, all_reviews)


def _build_final_report(snapshot: RepoSnapshot, all_reviews: list[ModelReview]) -> ReviewReport:
    all_issues = _merge_issues(all_reviews)

    available_scores = [r.risk_score for r in all_reviews if r.enabled and not r.error]
    if available_scores:
        overall_risk_score = int(sum(available_scores) / len(available_scores))
    else:
        overall_risk_score = all_reviews[0].risk_score if all_reviews else 50

    strengths: list[str] = []
    for review in all_reviews:
        strengths.extend(review.strengths)
    strengths = list(dict.fromkeys(strengths))[:8]

    quick_wins = _compute_quick_wins(all_issues)
    executive_summary = _build_executive_summary(snapshot, all_issues, overall_risk_score)

    coverage = {
        "models_attempted": len(all_reviews),
        "models_responded": sum(1 for r in all_reviews if r.enabled and not r.error),
        "models_failed_or_unavailable": [
            {"model": r.model_name, "error": r.error} for r in all_reviews if (not r.enabled or r.error)
        ],
        "files_analyzed": snapshot.stats.get("total_files_analyzed", 0),
        "languages": snapshot.stats.get("languages", {}),
    }

    markdown_report = build_markdown_report(
        repository=snapshot.repo_name,
        branch=snapshot.branch,
        commit=snapshot.commit,
        overall_risk_score=overall_risk_score,
        executive_summary=executive_summary,
        strengths=strengths,
        issues=all_issues,
        model_reviews=all_reviews,
        coverage=coverage,
        quick_wins=quick_wins,
    )

    return ReviewReport(
        repository=snapshot.repo_name,
        branch=snapshot.branch,
        commit=snapshot.commit,
        executive_summary=executive_summary,
        overall_risk_score=overall_risk_score,
        strengths=strengths,
        key_findings=all_issues,
        model_reviews=all_reviews,
        coverage=coverage,
        quick_wins=quick_wins,
        markdown_report=markdown_report,
    )


async def generate_review_report_progressive(
    snapshot: RepoSnapshot,
    on_update: Callable[[dict], Awaitable[None]],
) -> ReviewReport:
    static_review = run_static_analysis(snapshot.file_summaries)
    providers = get_default_providers()

    repo_context = {
        "repo_name": snapshot.repo_name,
        "branch": snapshot.branch,
        "commit": snapshot.commit,
        "stats": snapshot.stats,
        "files": [
            {
                "path": f["path"],
                "language": f["language"],
                "size_chars": f["size_chars"],
                "line_count": f["line_count"],
                "content": f["content"],
            }
            for f in snapshot.file_summaries
        ],
    }

    all_reviews: list[ModelReview] = [static_review]
    await on_update(
        {
            "stage": "static_analysis_completed",
            "model_name": "Static Rules Engine",
            "model_status": "completed",
            "completed_models": 1,
            "total_models": len(providers) + 1,
            "report": _build_final_report(snapshot, all_reviews).model_dump(),
        }
    )

    for index, provider in enumerate(providers, start=2):
        await on_update(
            {
                "stage": f"{provider.name.lower().replace(' ', '_')}_running",
                "model_name": provider.name,
                "model_status": "running",
                "completed_models": index - 1,
                "total_models": len(providers) + 1,
                "report": _build_final_report(snapshot, all_reviews).model_dump(),
            }
        )

        review = await provider.review(repo_context)
        all_reviews.append(review)
        status = "completed"
        if review.error and review.enabled:
            status = "failed"
        elif not review.enabled:
            status = "unavailable"

        await on_update(
            {
                "stage": f"{provider.name.lower().replace(' ', '_')}_completed",
                "model_name": provider.name,
                "model_status": status,
                "completed_models": index,
                "total_models": len(providers) + 1,
                "report": _build_final_report(snapshot, all_reviews).model_dump(),
            }
        )

    return _build_final_report(snapshot, all_reviews)
