"""Domain models for the ChatGPT backup manager."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional
import threading

from pydantic import BaseModel


class JobStatus(str, Enum):
    """Lifecycle states for a backup ingestion job."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Job:
    """Represents the state of a backup processing job."""

    id: str
    url: str
    archive_path: Path
    extract_path: Path
    index_path: Path
    status: JobStatus = JobStatus.PENDING
    stage: str = "pending"
    stage_detail: Optional[str] = None
    progress: Optional[float] = None
    bytes_downloaded: int = 0
    total_bytes: Optional[int] = None
    message: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def update(self, **fields: Any) -> None:
        """Safely update fields on the job."""

        with self.lock:
            for key, value in fields.items():
                if not hasattr(self, key):
                    raise AttributeError(f"Job has no attribute '{key}'")
                setattr(self, key, value)
            self.updated_at = datetime.utcnow()

    def set_total_bytes(self, total: Optional[int]) -> None:
        with self.lock:
            self.total_bytes = total
            self.progress = (self.bytes_downloaded / total) if total else None
            self.updated_at = datetime.utcnow()

    def bump_downloaded(self, amount: int) -> None:
        with self.lock:
            self.bytes_downloaded += amount
            if self.total_bytes:
                self.progress = min(self.bytes_downloaded / self.total_bytes, 1.0)
            self.updated_at = datetime.utcnow()

    def set_progress(self, progress: Optional[float], detail: Optional[str] = None) -> None:
        with self.lock:
            self.progress = progress
            if detail is not None:
                self.stage_detail = detail
            self.updated_at = datetime.utcnow()

    def set_stage(self, stage: str, status: Optional[JobStatus] = None, detail: Optional[str] = None) -> None:
        with self.lock:
            self.stage = stage
            if status is not None:
                self.status = status
            if detail is not None:
                self.stage_detail = detail
            self.updated_at = datetime.utcnow()

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the job state."""

        with self.lock:
            return {
                "id": self.id,
                "url": self.url,
                "status": self.status.value,
                "stage": self.stage,
                "stage_detail": self.stage_detail,
                "progress": self.progress,
                "bytes_downloaded": self.bytes_downloaded,
                "total_bytes": self.total_bytes,
                "message": self.message,
                "archive_path": str(self.archive_path),
                "extract_path": str(self.extract_path),
                "index_path": str(self.index_path),
                "created_at": self.created_at.isoformat() + "Z",
                "updated_at": self.updated_at.isoformat() + "Z",
            }


class JobInfo(BaseModel):
    """Public API view of a job."""

    id: str
    url: str
    status: JobStatus
    stage: str
    stage_detail: Optional[str] = None
    progress: Optional[float] = None
    bytes_downloaded: int
    total_bytes: Optional[int] = None
    message: Optional[str] = None
    archive_path: str
    extract_path: str
    index_path: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_job(cls, job: Job) -> "JobInfo":
        data = job.snapshot()
        created_at = _parse_iso8601(data["created_at"])
        updated_at = _parse_iso8601(data["updated_at"])
        return cls(
            id=data["id"],
            url=data["url"],
            status=JobStatus(data["status"]),
            stage=data["stage"],
            stage_detail=data["stage_detail"],
            progress=data["progress"],
            bytes_downloaded=data["bytes_downloaded"],
            total_bytes=data["total_bytes"],
            message=data["message"],
            archive_path=data["archive_path"],
            extract_path=data["extract_path"],
            index_path=data["index_path"],
            created_at=created_at,
            updated_at=updated_at,
        )


def _parse_iso8601(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)
