from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .models import RepoSnapshot

ALLOWED_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".cpp",
    ".c",
    ".h",
    ".cs",
    ".php",
    ".rb",
    ".swift",
    ".kt",
    ".scala",
    ".sql",
    ".yaml",
    ".yml",
    ".toml",
    ".json",
    ".md",
}

IGNORED_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    ".next",
    "target",
    "venv",
    ".venv",
    "__pycache__",
    ".idea",
    ".vscode",
}


class RepositoryIngestionError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RepositoryIngestionError(proc.stderr.strip() or "Git command failed")
    return proc.stdout.strip()


def clone_and_snapshot(
    repo_url: str,
    branch: str | None = None,
    max_files: int = 25,
    max_file_chars: int = 12000,
) -> tuple[RepoSnapshot, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="reviewlab_"))
    clone_args = ["clone", "--depth", "1"]
    if branch:
        clone_args.extend(["--branch", branch])
    clone_args.extend([repo_url, str(temp_dir)])
    _run_git(clone_args)

    active_branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=temp_dir)
    commit = _run_git(["rev-parse", "HEAD"], cwd=temp_dir)

    files = []
    total_chars = 0
    total_lines = 0
    language_count: dict[str, int] = {}

    for path in temp_dir.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        if len(files) >= max_files:
            break

        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        trimmed_content = content[:max_file_chars]
        relative = str(path.relative_to(temp_dir))
        line_count = content.count("\n") + 1
        total_lines += line_count
        total_chars += len(content)
        language = path.suffix.lower().lstrip(".") or "other"
        language_count[language] = language_count.get(language, 0) + 1

        files.append(
            {
                "path": relative,
                "language": language,
                "size_chars": len(content),
                "line_count": line_count,
                "content": trimmed_content,
            }
        )

    snapshot = RepoSnapshot(
        repo_name=repo_url.rstrip("/").split("/")[-1].replace(".git", ""),
        branch=active_branch,
        commit=commit,
        file_summaries=files,
        stats={
            "total_files_analyzed": len(files),
            "total_characters": total_chars,
            "total_lines": total_lines,
            "languages": language_count,
        },
    )
    return snapshot, temp_dir


def cleanup_repository(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
