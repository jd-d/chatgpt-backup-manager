"""Regression tests for JobManager restart behaviour."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app import config
from app.manager import JobManager
from app.models import Job, JobStatus


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch) -> Path:
    data_dir = tmp_path / "data"
    downloads = data_dir / "downloads"
    extracted = data_dir / "extracted"
    indexes = data_dir / "indexes"
    tmp_dir = data_dir / "tmp"
    for path in (data_dir, downloads, extracted, indexes, tmp_dir):
        path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "DOWNLOAD_DIR", downloads)
    monkeypatch.setattr(config, "EXTRACT_DIR", extracted)
    monkeypatch.setattr(config, "INDEX_DIR", indexes)
    monkeypatch.setattr(config, "TMP_DIR", tmp_dir)
    return data_dir


def test_restart_requeues_incomplete_jobs(isolated_data_dir: Path, monkeypatch) -> None:
    async def run() -> None:
        job = Job(
            id="job123",
            url="https://example.com/archive.zip",
            archive_path=config.DOWNLOAD_DIR / "job123.zip",
            extract_path=config.EXTRACT_DIR / "job123",
            index_path=config.INDEX_DIR / "job123.sqlite3",
            status=JobStatus.DOWNLOADING,
            stage="downloading",
            stage_detail="Halfway",
            progress=0.5,
            bytes_downloaded=128,
            total_bytes=256,
        )
        jobs_file = config.DATA_DIR / "jobs.json"
        jobs_file.write_text(json.dumps([job.snapshot()]), encoding="utf-8")

        manager = JobManager()

        run_calls: list[str] = []

        async def fake_run(resumed_job: Job) -> None:
            run_calls.append(resumed_job.id)

        monkeypatch.setattr(manager, "_run_job", fake_run)

        await manager.startup()
        await asyncio.sleep(0)

        assert run_calls == [job.id]

        info = await manager.get_job(job.id)
        assert info is not None
        assert info.status == JobStatus.PENDING
        assert info.stage == "queued"
        assert info.stage_detail == "Re-queued after restart"
        assert info.message == "Job automatically re-queued after restart"

        persisted = json.loads(jobs_file.read_text(encoding="utf-8"))
        assert persisted[0]["status"] == JobStatus.PENDING.value
        assert persisted[0]["stage"] == "queued"
        assert persisted[0]["message"] == "Job automatically re-queued after restart"

    asyncio.run(run())


def test_restart_marks_jobs_failed_without_source(isolated_data_dir: Path) -> None:
    async def run() -> None:
        job = Job(
            id="missing-url",
            url="",
            archive_path=config.DOWNLOAD_DIR / "missing-url.zip",
            extract_path=config.EXTRACT_DIR / "missing-url",
            index_path=config.INDEX_DIR / "missing-url.sqlite3",
            status=JobStatus.DOWNLOADING,
            stage="downloading",
        )
        jobs_file = config.DATA_DIR / "jobs.json"
        jobs_file.write_text(json.dumps([job.snapshot()]), encoding="utf-8")

        manager = JobManager()
        await manager.startup()

        info = await manager.get_job(job.id)
        assert info is not None
        assert info.status == JobStatus.FAILED
        assert info.stage == "failed"
        assert info.stage_detail == "Missing source URL; cannot resume"
        assert info.message == "Job missing source URL when restarting"

        persisted = json.loads(jobs_file.read_text(encoding="utf-8"))
        assert persisted[0]["status"] == JobStatus.FAILED.value
        assert persisted[0]["stage"] == "failed"
        assert persisted[0]["message"] == "Job missing source URL when restarting"

    asyncio.run(run())
