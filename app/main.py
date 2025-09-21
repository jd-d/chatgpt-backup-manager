"""Entry point for the FastAPI application."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .manager import JobManager
from .models import JobInfo

app = FastAPI(title="ChatGPT Backup Manager", version="0.1.0")
templates = Jinja2Templates(directory="templates")
manager = JobManager()


async def get_manager() -> JobManager:
    return manager


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, manager: JobManager = Depends(get_manager)) -> HTMLResponse:
    jobs = await manager.list_jobs()
    return templates.TemplateResponse("index.html", {"request": request, "jobs": jobs})


@app.post("/jobs", response_class=HTMLResponse)
async def create_job(
    request: Request,
    url: str = Form(..., description="Direct download link to the ChatGPT backup archive"),
    manager: JobManager = Depends(get_manager),
) -> RedirectResponse:
    job = await manager.create_job(url.strip())
    return RedirectResponse(url=request.url_for("job_detail", job_id=job.id), status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str, manager: JobManager = Depends(get_manager)) -> HTMLResponse:
    job = await manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse("job.html", {"request": request, "job": job})


@app.get("/search", response_class=HTMLResponse)
async def search(
    request: Request,
    job_id: str | None = None,
    q: str | None = None,
    manager: JobManager = Depends(get_manager),
) -> HTMLResponse:
    jobs = await manager.list_jobs()
    selected_job: JobInfo | None = None
    results = []
    error = None
    if job_id:
        selected_job = next((job for job in jobs if job.id == job_id), None)
        if not selected_job:
            error = "Unknown job selected"
        elif q:
            try:
                results = await manager.search(job_id, q)
            except Exception as exc:  # pragma: no cover - surfaces to UI
                error = str(exc)
    context = {
        "request": request,
        "jobs": jobs,
        "selected_job": selected_job,
        "query": q or "",
        "results": results,
        "error": error,
    }
    return templates.TemplateResponse("search.html", context)


# API endpoints -------------------------------------------------------------


@app.get("/api/jobs")
async def api_list_jobs(manager: JobManager = Depends(get_manager)):
    jobs = await manager.list_jobs()
    return [job.dict() for job in jobs]


@app.get("/api/jobs/{job_id}")
async def api_get_job(job_id: str, manager: JobManager = Depends(get_manager)):
    job = await manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.dict()


@app.get("/api/jobs/{job_id}/search")
async def api_search(job_id: str, q: str, manager: JobManager = Depends(get_manager)):
    try:
        results = await manager.search(job_id, q)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return results
