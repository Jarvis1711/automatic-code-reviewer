from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl
from starlette.requests import Request

from .services.orchestrator import generate_review_report, generate_review_report_progressive
from .services.providers import get_default_providers
from .services.repository import RepositoryIngestionError, cleanup_repository, clone_and_snapshot

app = FastAPI(title="ReviewVerse", version="1.0.0")
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")
if not os.getenv("OPENAI_API_KEY") and not os.getenv("ANTHROPIC_API_KEY") and not os.getenv("GROQ_API_KEY"):
    load_dotenv(BASE_DIR / ".env.example", override=False)

app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


REVIEW_JOBS: dict[str, dict] = {}


class ReviewRequest(BaseModel):
    repo_url: HttpUrl
    branch: str | None = None


async def _run_review_job(job_id: str, payload: ReviewRequest) -> None:
    max_files = int(os.getenv("MAX_FILES", "25"))
    max_file_chars = int(os.getenv("MAX_FILE_CHARS", "12000"))

    local_path = None
    try:
        REVIEW_JOBS[job_id].update({"status": "running", "stage": "cloning_repository", "progress": 10})
        snapshot, local_path = clone_and_snapshot(
            repo_url=str(payload.repo_url),
            branch=payload.branch,
            max_files=max_files,
            max_file_chars=max_file_chars,
        )

        REVIEW_JOBS[job_id].update(
            {
                "status": "running",
                "stage": "analyzing_models",
                "progress": 30,
                "snapshot": {
                    "repository": snapshot.repo_name,
                    "branch": snapshot.branch,
                    "commit": snapshot.commit,
                    "files": snapshot.stats.get("total_files_analyzed", 0),
                },
            }
        )

        async def _on_update(update: dict) -> None:
            completed = int(update.get("completed_models", 0))
            total = int(update.get("total_models", 1))
            progress = min(95, 30 + int((completed / max(total, 1)) * 60))

            model_name = update.get("model_name")
            model_status = update.get("model_status")
            if model_name and model_status:
                statuses = REVIEW_JOBS[job_id].get("model_statuses", [])
                found = False
                for item in statuses:
                    if item.get("name") == model_name:
                        item["status"] = model_status
                        found = True
                        break
                if not found:
                    statuses.append({"name": model_name, "status": model_status})

            REVIEW_JOBS[job_id].update(
                {
                    "status": "running",
                    "stage": update.get("stage", "analyzing_models"),
                    "progress": progress,
                    "partial_report": update.get("report"),
                    "completed_models": completed,
                    "total_models": total,
                }
            )

        report = await generate_review_report_progressive(snapshot, _on_update)

        final_statuses = []
        for review in report.model_reviews:
            if not review.enabled:
                status = "unavailable"
            elif review.error:
                status = "failed"
            else:
                status = "completed"
            final_statuses.append({"name": review.model_name, "status": status})

        REVIEW_JOBS[job_id].update(
            {
                "status": "completed",
                "stage": "completed",
                "progress": 100,
                "model_statuses": final_statuses,
                "partial_report": report.model_dump(),
                "report": report.model_dump(),
            }
        )
    except RepositoryIngestionError as exc:
        REVIEW_JOBS[job_id].update({"status": "failed", "stage": "failed", "error": str(exc)})
    except Exception as exc:
        REVIEW_JOBS[job_id].update({"status": "failed", "stage": "failed", "error": f"Review generation failed: {exc}"})
    finally:
        if local_path:
            cleanup_repository(local_path)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request, "app_name": "ReviewVerse"})


@app.post("/api/review")
async def review_repository(payload: ReviewRequest):
    max_files = int(os.getenv("MAX_FILES", "25"))
    max_file_chars = int(os.getenv("MAX_FILE_CHARS", "12000"))

    local_path = None
    try:
        snapshot, local_path = clone_and_snapshot(
            repo_url=str(payload.repo_url),
            branch=payload.branch,
            max_files=max_files,
            max_file_chars=max_file_chars,
        )
        report = await generate_review_report(snapshot)
        return report.model_dump()
    except RepositoryIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Review generation failed: {exc}") from exc
    finally:
        if local_path:
            cleanup_repository(local_path)


@app.post("/api/review/start")
async def start_review(payload: ReviewRequest):
    job_id = str(uuid.uuid4())
    provider_names = [provider.name for provider in get_default_providers()]
    model_statuses = [{"name": "Static Rules Engine", "status": "queued"}] + [
        {"name": name, "status": "queued"} for name in provider_names
    ]
    REVIEW_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
        "completed_models": 0,
        "total_models": 0,
        "model_statuses": model_statuses,
        "partial_report": None,
        "report": None,
        "error": None,
    }
    asyncio.create_task(_run_review_job(job_id, payload))
    return {"job_id": job_id}


@app.get("/api/review/{job_id}")
async def get_review_status(job_id: str):
    job = REVIEW_JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/health")
async def health():
    return {"status": "ok"}
