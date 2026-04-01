from __future__ import annotations

from collections import defaultdict

from .models import ModelReview, ReviewIssue


def build_markdown_report(
    repository: str,
    branch: str,
    commit: str,
    overall_risk_score: int,
    executive_summary: str,
    strengths: list[str],
    issues: list[ReviewIssue],
    model_reviews: list[ModelReview],
    coverage: dict,
    quick_wins: list[str],
) -> str:
    grouped: dict[str, list[ReviewIssue]] = defaultdict(list)
    for issue in issues:
        grouped[issue.severity].append(issue)

    lines: list[str] = [
        f"# Automated Multi-LLM Code Review: {repository}",
        "",
        "## Repository Snapshot",
        f"- Branch: {branch}",
        f"- Commit: {commit}",
        f"- Overall Risk Score: {overall_risk_score}/100",
        "",
        "## Executive Summary",
        executive_summary,
        "",
        "## Strengths",
    ]

    lines.extend([f"- {s}" for s in strengths] or ["- No explicit strengths were returned."])

    lines.append("")
    lines.append("## Coverage & Reliability")
    lines.append(f"- Models attempted: {coverage.get('models_attempted', 0)}")
    lines.append(f"- Models responded: {coverage.get('models_responded', 0)}")
    lines.append(f"- Files analyzed: {coverage.get('files_analyzed', 0)}")
    lines.append(f"- Languages: {coverage.get('languages', {})}")

    failures = coverage.get("models_failed_or_unavailable", [])
    if failures:
        lines.append("- Model availability issues:")
        for failure in failures:
            lines.append(f"  - {failure.get('model', 'unknown')}: {failure.get('error', 'unavailable')}")

    lines.append("")
    lines.append("## Findings by Severity")
    for severity in ["critical", "high", "medium", "low"]:
        items = grouped.get(severity, [])
        lines.append(f"### {severity.capitalize()} ({len(items)})")
        if not items:
            lines.append("- None")
        else:
            for issue in items:
                location = f"{issue.file}:{issue.line}" if issue.line else issue.file
                lines.extend(
                    [
                        f"- **{issue.title}** [{location}]",
                        f"  - Category: {issue.category}",
                        f"  - Suggestion: {issue.suggestion}",
                        f"  - Rationale: {issue.rationale}",
                        f"  - Confidence: {issue.confidence:.2f}",
                        f"  - Source model: {issue.source_model}",
                    ]
                )

    lines.append("")
    lines.append("## Model-by-Model Output")
    for review in model_reviews:
        lines.append(f"### {review.model_name}")
        lines.append(f"- Family: {review.family}")
        lines.append(f"- Enabled: {review.enabled}")
        lines.append(f"- Risk score: {review.risk_score}")
        if review.error:
            lines.append(f"- Error: {review.error}")
        lines.append(f"- Summary: {review.summary or 'No summary returned.'}")
        if review.strengths:
            lines.append("- Strengths:")
            for strength in review.strengths:
                lines.append(f"  - {strength}")
        lines.append(f"- Issues surfaced: {len(review.issues)}")
        for issue in review.issues:
            location = f"{issue.file}:{issue.line}" if issue.line else issue.file
            lines.append(
                f"  - [{issue.severity.upper()}] {issue.title} ({location}) | {issue.category} | conf={issue.confidence:.2f}"
            )
        if review.raw_response:
            lines.append("- Raw response (truncated):")
            lines.append("```json")
            lines.append(review.raw_response[:2500])
            lines.append("```")
        lines.append("")

    lines.append("")
    lines.append("## Quick Wins")
    lines.extend([f"- {w}" for w in quick_wins] or ["- No quick wins available."])

    return "\n".join(lines)
