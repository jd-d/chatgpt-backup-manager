"""Archive extraction helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZipFile

from .models import Job


def extract_archive(job: Job) -> None:
    """Unpack the downloaded archive into the job's extraction directory."""

    extract_path = job.extract_path
    extract_path.mkdir(parents=True, exist_ok=True)

    if any(extract_path.iterdir()):
        _clear_directory(extract_path)

    with ZipFile(job.archive_path) as archive:
        members = archive.infolist()
        total = len(members)
        for index, member in enumerate(members, start=1):
            _extract_member(archive, member, extract_path)
            if total:
                progress = index / total
                detail = f"Extracted {index}/{total} entries"
                job.set_progress(progress, detail=detail)


def _clear_directory(path: Path) -> None:
    for item in path.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _extract_member(archive: ZipFile, member, target_dir: Path) -> None:
    target_path = _safe_destination(target_dir, member.filename)
    if member.is_dir():
        target_path.mkdir(parents=True, exist_ok=True)
        return
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with archive.open(member, "r") as src, target_path.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=1024 * 1024)


def _safe_destination(base_dir: Path, name: str) -> Path:
    destination = base_dir / name
    resolved = destination.resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ValueError(f"Archive member escapes extraction directory: {name}")
    return resolved
