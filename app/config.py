"""Application configuration utilities."""

from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "data"
DOWNLOAD_DIR = DATA_DIR / "downloads"
EXTRACT_DIR = DATA_DIR / "extracted"
INDEX_DIR = DATA_DIR / "indexes"
TMP_DIR = DATA_DIR / "tmp"

for directory in (DATA_DIR, DOWNLOAD_DIR, EXTRACT_DIR, INDEX_DIR, TMP_DIR):
    directory.mkdir(parents=True, exist_ok=True)

DEFAULT_DOWNLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MiB
