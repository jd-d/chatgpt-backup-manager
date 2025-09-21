# ChatGPT Backup Manager

A web-based, text-first control panel for taming humongous ChatGPT backup archives. Point the app at the
download link from OpenAI, let it stream the giant zip, unpack it without freezing your machine, and build
a fast search index for all of your conversations.

## Features

- **Reliable download manager** – Streams massive archives directly to disk with retry and resume support.
- **Responsive unpacking** – Extracts the archive in a background worker thread, updating progress as it goes.
- **Searchable index** – Builds a SQLite FTS5 index of the exported conversations so queries return instantly.
- **Text-centric UI** – Minimalist monospace interface that keeps everything legible and lightweight.
- **REST API** – Access job status and search results programmatically.

## Getting started

1. Install dependencies (Python 3.11+):

   ```bash
   pip install -e .
   ```

2. Launch the development server:

   ```bash
   uvicorn app.main:app --reload
   ```

3. Open `http://127.0.0.1:8000` in your browser. Paste the download URL from the OpenAI export email and
   watch the job progress through download, extraction, and indexing.

4. Once indexing is complete, head to the **Search** view, choose the finished job, and query your history.

### CLI / API

- `GET /api/jobs` – list tracked jobs.
- `GET /api/jobs/{job_id}` – detailed job information.
- `GET /api/jobs/{job_id}/search?q=...` – search within a completed backup.

## Project layout

```
app/
  archive.py     # extraction helpers
  config.py      # shared paths and constants
  indexer.py     # FTS5 index builder and query helpers
  main.py        # FastAPI application and routes
  manager.py     # job orchestration (download/extract/index)
  models.py      # job dataclasses and Pydantic schemas
  utils.py       # misc helpers
templates/       # text-based UI templates
```

All persistent data (downloads, extracted archives, indexes) live under `data/` next to the source tree.
The directories are created automatically on first run and are excluded from version control.
