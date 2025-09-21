"""Background processing manager for backup ingestion jobs."""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional
from uuid import uuid4

import httpx

from . import config, indexer
from .archive import extract_archive
from .models import Job, JobInfo, JobStatus
from .utils import human_readable_bytes

logger = logging.getLogger(__name__)


class JobManager:
    """Coordinates download, extraction, and indexing of backups."""

    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, url: str) -> Job:
        job_id = uuid4().hex
        archive_path = config.DOWNLOAD_DIR / f"{job_id}.zip"
        extract_path = config.EXTRACT_DIR / job_id
        index_path = config.INDEX_DIR / f"{job_id}.sqlite3"
        job = Job(
            id=job_id,
            url=url,
            archive_path=archive_path,
            extract_path=extract_path,
            index_path=index_path,
        )
        async with self._lock:
            self._jobs[job_id] = job
        asyncio.create_task(self._run_job(job))
        return job

    async def list_jobs(self) -> List[JobInfo]:
        async with self._lock:
            jobs = list(self._jobs.values())
        return [JobInfo.from_job(job) for job in jobs]

    async def get_job(self, job_id: str) -> Optional[JobInfo]:
        async with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        return JobInfo.from_job(job)

    async def get_job_internal(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def search(self, job_id: str, query: str, limit: int = 25) -> List[dict[str, str]]:
        job = await self.get_job_internal(job_id)
        if not job:
            raise KeyError(f"No job with id {job_id}")
        if job.status != JobStatus.COMPLETED:
            raise RuntimeError("Job has not completed indexing yet")
        return indexer.query_index(job.index_path, query, limit)

    async def _run_job(self, job: Job) -> None:
        try:
            job.set_stage("queued", JobStatus.PENDING, detail="Awaiting processing")
            await asyncio.sleep(0)
            await self._download(job)
            job.set_stage("downloaded", JobStatus.DOWNLOADED, detail="Archive downloaded")
            await self._extract(job)
            job.set_stage("extracted", JobStatus.EXTRACTED, detail="Files unpacked")
            await self._index(job)
            job.set_stage("completed", JobStatus.COMPLETED, detail="Index ready")
            job.set_progress(1.0)
        except Exception as exc:  # pragma: no cover - safety net
            logger.exception("Job %s failed", job.id)
            job.set_stage("failed", JobStatus.FAILED, detail=str(exc))
            job.update(message=str(exc))

    async def _download(self, job: Job) -> None:
        job.set_stage("downloading", JobStatus.DOWNLOADING, detail="Starting download")
        job.set_progress(0.0)
        retries = 3
        backoff = 2
        last_error: Optional[Exception] = None
        for attempt in range(1, retries + 1):
            try:
                await self._stream_download(job)
                return
            except Exception as exc:
                last_error = exc
                wait_for = backoff ** attempt
                job.set_stage(
                    "downloading",
                    detail=f"Retry {attempt}/{retries} after error: {exc}"
                )
                await asyncio.sleep(wait_for)
        raise RuntimeError(f"Download failed after {retries} attempts: {last_error}")

    async def _stream_download(self, job: Job) -> None:
        resume_position = 0
        if job.archive_path.exists():
            resume_position = job.archive_path.stat().st_size

        headers = {"User-Agent": "ChatGPT-Backup-Manager/1.0"}
        if resume_position:
            headers["Range"] = f"bytes={resume_position}-"

        async with httpx.AsyncClient(timeout=None, follow_redirects=True) as client:
            async with client.stream("GET", job.url, headers=headers) as response:
                response.raise_for_status()
                if resume_position and response.status_code != 206:
                    # Server ignored the range request; restart from scratch
                    resume_position = 0
                    headers.pop("Range", None)
                    if job.archive_path.exists():
                        job.archive_path.unlink()
                    job.update(bytes_downloaded=0)
                total = response.headers.get("Content-Length")
                if total is not None:
                    total_bytes = int(total)
                    if resume_position and response.status_code == 206:
                        total_bytes += resume_position
                else:
                    total_bytes = None
                job.set_total_bytes(total_bytes)
                if resume_position:
                    job.update(bytes_downloaded=resume_position)
                mode = "ab" if resume_position else "wb"
                with open(job.archive_path, mode) as file_handle:
                    async for chunk in response.aiter_bytes(config.DEFAULT_DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue
                        file_handle.write(chunk)
                        job.bump_downloaded(len(chunk))
                        detail = _format_download_detail(job)
                        job.set_progress(job.progress, detail=detail)
                        await asyncio.sleep(0)

    async def _extract(self, job: Job) -> None:
        job.set_stage("extracting", JobStatus.EXTRACTING, detail="Unpacking archive")
        job.set_progress(0.0)
        await asyncio.to_thread(extract_archive, job)
        job.set_progress(1.0, detail="Extraction complete")

    async def _index(self, job: Job) -> None:
        job.set_stage("indexing", JobStatus.INDEXING, detail="Creating search index")
        job.set_progress(0.0)
        await asyncio.to_thread(indexer.build_index_for_job, job)
        job.set_progress(1.0, detail="Indexing finished")


def _format_download_detail(job: Job) -> str:
    with job.lock:
        downloaded = job.bytes_downloaded
        total = job.total_bytes
    if total:
        return f"{human_readable_bytes(downloaded)} / {human_readable_bytes(total)}"
    return f"{human_readable_bytes(downloaded)} downloaded"
