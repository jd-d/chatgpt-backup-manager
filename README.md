# ChatGPT Backup Manager

A text-first control panel for taming humongous ChatGPT export archives. Point the app at the
download link OpenAI emails you, let it stream the giant zip straight to disk, and watch as the
system unpacks, indexes, and exposes the entire history through both a lightweight UI and a REST API.

- **Why it exists** – The official export can easily be tens of gigabytes. Naïvely downloading and
  extracting that archive will freeze a browser and overwhelm a laptop. This project keeps each
  operation isolated, resumable, and observable so you can safely wrangle the data on your own
  machine.
- **Who it is for** – People who want to audit, search, or migrate their ChatGPT history without
  surrendering the archive to a third-party service.

## Table of contents

1. [Feature highlights](#feature-highlights)
2. [How the pipeline works](#how-the-pipeline-works)
3. [Architecture tour](#architecture-tour)
4. [Storage layout](#storage-layout)
5. [Using the web interface](#using-the-web-interface)
6. [Calling the REST API](#calling-the-rest-api)
7. [Running the project locally](#running-the-project-locally)
8. [Testing](#testing)
9. [Troubleshooting and operational notes](#troubleshooting-and-operational-notes)
10. [Project layout](#project-layout)

## Feature highlights

- **Reliable download manager** – Streams the export directly to `data/downloads/` using an
  `httpx.AsyncClient` with Range support, retry backoff, and byte-level progress updates so that lost
  connections automatically resume instead of restarting from scratch.
- **Responsive unpacking** – Offloads archive extraction to a worker thread, sanitises filenames, and
  reports per-entry progress so the UI stays snappy even while millions of files are being written to
  disk.
- **Searchable index** – Builds a SQLite FTS5 database from either the official `conversations.json`
  file or any text/JSON/Markdown files in the export directory, normalises message content, and
  exposes instant full-text search results with highlighted snippets.
- **Job persistence & restart safety** – Serialises every job to `data/jobs.json`, reloads unfinished
  work on startup, and automatically re-queues downloads so that an unexpected shutdown does not cost
  hours of processing.
- **Text-centric UI & API** – Ships with minimalist Jinja templates optimised for monochrome
  terminals, plus JSON endpoints for automation or integration with other tooling.

## How the pipeline works

Every backup you ingest moves through the same set of well-defined stages:

1. **Queued** – A job is created when you submit a URL. The `JobManager` stores the target download,
   allocates paths for the archive, extraction directory, and index, and persists the initial
   snapshot.
2. **Downloading** – The manager streams the zip in 1 MiB chunks, updating `bytes_downloaded`,
   progress percentages, and human-readable status text ("512.0 MiB / 5.3 GiB"). Retries happen with
   exponential backoff when the remote server hiccups.
3. **Extracting** – Once the file lands, the archive worker clears any previous extraction directory
   and safely expands each entry using `ZipFile`, rejecting malicious paths that attempt directory
   traversal.
4. **Indexing** – Finally, the indexer parses the exported conversations (or falls back to walking the
   extracted tree), flattening messages and metadata into an FTS5 table to power sub-second keyword
   search.
5. **Completed** – The job persists with stage `completed`, progress `1.0`, and the UI/API both expose
   the search endpoint. Failed jobs retain the error message so you can diagnose issues.

All stage transitions, timestamps, and error messages live on the `Job` dataclass and are persisted to
JSON snapshots so that, if the server restarts midway through a download or index build, the job comes
back in a safe "re-queued" state instead of silently failing.

## Architecture tour

| Component | Responsibility |
|-----------|----------------|
| `FastAPI` application (`app/main.py`) | Serves HTML and JSON routes, wires dependency injection for the shared `JobManager`, and converts user input into job operations. |
| `JobManager` (`app/manager.py`) | Coordinates asynchronous downloads, extraction, indexing, persistence, and resumable state transitions for each job. |
| `Job`/`JobInfo` models (`app/models.py`) | Represent job state, enforce thread-safe mutations, expose serialisable snapshots, and provide typed responses for API clients. |
| Archive helpers (`app/archive.py`) | Ensure safe zip extraction with progress updates and directory hygiene. |
| Indexer (`app/indexer.py`) | Creates the SQLite FTS schema, imports conversation data, and answers search queries with highlighted snippets. |
| Templates (`templates/*.html`) | Provide the monochrome, monospace web interface without any client-side JavaScript. |

The system leans on asyncio to keep the FastAPI event loop responsive while heavyweight tasks run in
background threads via `asyncio.to_thread`. Download progress updates flow through the shared `Job`
instances, and persisted snapshots ensure that the state can be rebuilt on startup before accepting
new work.

## Storage layout

All runtime state lives under `data/` next to the source tree (created automatically on first run):

```
data/
  downloads/   # streamed .zip files from OpenAI exports
  extracted/   # per-job directories containing the unpacked export
  indexes/     # SQLite databases powering FTS search
  tmp/         # scratch space reserved for future extensions
  jobs.json    # persisted job snapshots for crash-safe restarts
```

You can change these locations by customising the constants in `app/config.py` before launching the
server. Delete the directories to reclaim disk space or to reset the app.

## Using the web interface

1. **Home / ingest view (`/`)** – Paste the direct download URL from OpenAI. The job list below shows
   every tracked backup with live status, percentage bars, and quick access to the detail page.
2. **Job detail (`/jobs/{id}`)** – Inspect the current stage, bytes downloaded, filesystem paths, and
   timestamps. Completed jobs reveal a link to jump into the search screen.
3. **Search (`/search`)** – Pick a completed job from the dropdown and run full-text queries. The
   results include conversation titles, ISO 8601 timestamps, and FTS snippets that highlight the matched terms.

Everything is rendered server-side with semantic HTML and monospace styling so you can comfortably run
it alongside terminals or inside a remote VM without any asset pipeline.

## Calling the REST API

The API mirrors the web interface so you can automate ingestion and search.

- `GET /api/jobs` – Returns all known jobs, including their statuses, progress values, and filesystem
  paths. Example response:

  ```json
  [
    {
      "id": "6a0b...",
      "status": "completed",
      "stage": "completed",
      "progress": 1.0,
      "bytes_downloaded": 5368709120,
      "archive_path": "data/downloads/6a0b.zip",
      "index_path": "data/indexes/6a0b.sqlite3",
      "created_at": "2024-01-01T12:00:00Z"
    }
  ]
  ```
- `GET /api/jobs/{job_id}` – Fetch a single job. A `404` indicates an unknown identifier.
- `GET /api/jobs/{job_id}/search?q=...` – Query a completed job. Returns a list of `{conversation_id,
  title, timestamp, snippet}` dictionaries. A `400` is raised if the job has not finished indexing.

These handlers share the same manager instance as the UI, so job updates instantly reflect in API
responses.

## Running the project locally

1. **Prerequisites** – Python 3.11 or newer (the codebase uses `asyncio` features introduced in 3.11)
   and a working C compiler if you plan to install optional speedups.
2. **Install dependencies**:

   ```bash
   pip install -e .
   ```

   This pulls in FastAPI, httpx, uvicorn, and the other packages defined in `pyproject.toml`.
3. **Start the development server**:

   ```bash
   uvicorn app.main:app --reload
   ```

4. **Open the UI** – Visit `http://127.0.0.1:8000`. Paste the download link from the OpenAI export
   email and watch the job progress through download, extraction, and indexing. When it completes, head
   to the Search view to query your history.

The first run creates the `data/` directory tree automatically. You can safely stop and restart the
server at any time; in-progress jobs will resume from the last persisted state once `manager.startup()`
replays `jobs.json`.

## Testing

Run the unit test suite with:

```bash
pytest
```

The tests currently focus on persistence and restart behaviour for incomplete jobs.

## Troubleshooting and operational notes

- **Archive URL expires** – OpenAI links typically expire after 24 hours. If a download fails with a
  403, request a fresh export and create a new job.
- **Disk usage** – Completed jobs retain the original zip, extracted files, and index. Delete the job’s
  directories under `data/` to reclaim space once you no longer need them.
- **Unexpected shutdowns** – On restart, the manager re-queues any job that was not `completed` or
  `failed`, marking it as pending while preserving the diagnostic message for your records.
- **Manual ingestion** – Already have an extracted export? Place the directory under `data/extracted/`
  and run the indexer manually via `python -m app.indexer` (see the functions in `app/indexer.py`) or
  adapt the code to point at your data. All helper functions are pure and callable on their own.

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
tests/           # pytest suite for restart logic
```

Persistent runtime data lives in `data/` next to the source tree and is excluded from version control.
