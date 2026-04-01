from __future__ import annotations

import re
from collections import Counter

from .models import ModelReview, ReviewIssue


SECRET_PATTERNS = [
    (r"AKIA[0-9A-Z]{16}", "Possible AWS key committed"),
    (r"(?i)api[_-]?key\s*[:=]\s*['\"][^'\"]+['\"]", "Possible hardcoded API key"),
    (r"(?i)password\s*[:=]\s*['\"][^'\"]+['\"]", "Possible hardcoded password"),
]


def _severity_for_todo(content: str) -> str:
    lowered = content.lower()
    if "security" in lowered or "critical" in lowered:
        return "high"
    return "low"


def run_static_analysis(files: list[dict]) -> ModelReview:
    issues: list[ReviewIssue] = []
    strengths: list[str] = []
    category_counts = Counter()

    for file in files:
        path = file["path"]
        content = file["content"]

        for regex, message in SECRET_PATTERNS:
            for match in re.finditer(regex, content):
                line = content[: match.start()].count("\n") + 1
                issues.append(
                    ReviewIssue(
                        title=message,
                        severity="critical",
                        category="security",
                        file=path,
                        line=line,
                        suggestion="Move secrets into environment variables or secret manager and rotate exposed credentials.",
                        rationale="Committed secrets can be harvested and abused quickly.",
                        confidence=0.9,
                        source_model="static-rules",
                    )
                )
                category_counts["security"] += 1

        todo_matches = list(re.finditer(r"(?i)(TODO|FIXME|HACK):?.*", content))
        if todo_matches:
            for todo in todo_matches[:5]:
                line = content[: todo.start()].count("\n") + 1
                text = todo.group(0)
                sev = _severity_for_todo(text)
                issues.append(
                    ReviewIssue(
                        title="Unresolved technical debt marker",
                        severity=sev,
                        category="maintainability",
                        file=path,
                        line=line,
                        suggestion="Convert TODO/FIXME into tracked issues with owner and due date.",
                        rationale="Untracked debt accumulates and blocks predictable delivery.",
                        confidence=0.65,
                        source_model="static-rules",
                    )
                )
                category_counts["maintainability"] += 1

        long_lines = [ln for ln in content.splitlines() if len(ln) > 140]
        if len(long_lines) > 8:
            issues.append(
                ReviewIssue(
                    title="Multiple overlong lines reduce readability",
                    severity="low",
                    category="readability",
                    file=path,
                    suggestion="Wrap long lines and extract logic into named helper functions.",
                    rationale="Readable code shortens review time and lowers regression risk.",
                    confidence=0.55,
                    source_model="static-rules",
                )
            )
            category_counts["readability"] += 1

    if not issues:
        strengths.append("No obvious hardcoded secrets detected in sampled files.")
        strengths.append("Repository structure appears analyzable and organized.")
    else:
        strengths.append("Static review identified concrete improvement opportunities for quick remediation.")

    risk = 25 + min(70, len(issues) * 6)
    return ModelReview(
        model_name="Static Rules Engine",
        family="symbolic-analysis",
        enabled=True,
        summary="Pattern-based review focusing on security hygiene and maintainability signals.",
        strengths=strengths,
        issues=issues,
        risk_score=min(100, risk),
    )
