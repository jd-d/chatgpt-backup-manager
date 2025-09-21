"""Search index builder for ChatGPT backups."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from .models import Job


def build_index_for_job(job: Job) -> None:
    """Create or refresh the search index for a processed job."""

    build_index(job.extract_path, job.index_path, job)


def build_index(extracted_dir: Path, index_path: Path, job: Job | None = None) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(index_path)
    try:
        _initialise_schema(connection)
        connection.execute("DELETE FROM conversations")
        connection.commit()

        conversation_file = extracted_dir / "conversations.json"
        if conversation_file.exists():
            conversations = _load_conversations(conversation_file)
            _insert_conversations(connection, conversations, job)
        else:
            documents = list(_walk_text_documents(extracted_dir))
            _insert_documents(connection, documents, job)
        connection.commit()
    finally:
        connection.close()


def query_index(index_path: Path, query: str, limit: int = 25) -> List[dict[str, str]]:
    connection = sqlite3.connect(index_path)
    connection.row_factory = sqlite3.Row
    try:
        cursor = connection.execute(
            "SELECT conversation_id, title, timestamp, snippet(conversations, 3, '[', ']', '…', 10) AS snippet "
            "FROM conversations WHERE conversations MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        )
        rows = cursor.fetchall()
        return [
            {
                "conversation_id": row["conversation_id"],
                "title": row["title"],
                "timestamp": row["timestamp"],
                "snippet": row["snippet"],
            }
            for row in rows
        ]
    finally:
        connection.close()


def _initialise_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS conversations USING fts5(
            conversation_id UNINDEXED,
            title,
            timestamp,
            content
        )
        """
    )


def _load_conversations(path: Path) -> List[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("conversations", "items", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
    return []


def _insert_conversations(connection: sqlite3.Connection, conversations: List[dict], job: Job | None) -> None:
    total = len(conversations) or 1
    for index, conversation in enumerate(conversations, start=1):
        conv_id = str(conversation.get("id") or index)
        title = conversation.get("title") or f"Conversation {index}"
        timestamp = _format_timestamp(conversation.get("create_time") or conversation.get("update_time"))
        content = _conversation_to_text(conversation)
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, timestamp, content) VALUES (?, ?, ?, ?)",
            (conv_id, title, timestamp, content),
        )
        if job:
            progress = index / total
            detail = f"Indexed {index}/{total} conversations"
            job.set_progress(progress, detail=detail)


def _insert_documents(connection: sqlite3.Connection, documents: List[Tuple[str, str, str]], job: Job | None) -> None:
    total = len(documents) or 1
    for index, (identifier, title, content) in enumerate(documents, start=1):
        connection.execute(
            "INSERT INTO conversations (conversation_id, title, timestamp, content) VALUES (?, ?, ?, ?)",
            (identifier, title, "", content),
        )
        if job:
            progress = index / total
            detail = f"Indexed {index}/{total} documents"
            job.set_progress(progress, detail=detail)


def _conversation_to_text(conversation: dict) -> str:
    parts: List[str] = []
    title = conversation.get("title")
    if title:
        parts.append(str(title))
    mapping = conversation.get("mapping")
    if isinstance(mapping, dict):
        ordered_messages = _order_messages(mapping)
        for message in ordered_messages:
            role = message.get("author", {}).get("role", "unknown")
            text = _extract_message_text(message)
            if text:
                parts.append(f"{role}: {text}")
    return "\n\n".join(parts)


def _order_messages(mapping: dict) -> List[dict]:
    messages = []
    for node in mapping.values():
        message = node.get("message") if isinstance(node, dict) else None
        if message:
            messages.append(message)
    messages.sort(key=lambda m: m.get("create_time") or 0)
    return messages


def _extract_message_text(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, dict):
        if content.get("parts"):
            collected: List[str] = []
            for part in content["parts"]:
                text = _normalise_part(part)
                if text:
                    collected.append(text)
            return "\n".join(collected)
        if content.get("text"):
            return str(content["text"])
    if isinstance(content, list):
        collected = []
        for part in content:
            text = _normalise_part(part)
            if text:
                collected.append(text)
        return "\n".join(collected)
    if isinstance(content, str):
        return content
    return ""


def _normalise_part(part) -> str:
    if isinstance(part, str):
        return part.strip()
    if isinstance(part, dict):
        if "text" in part and isinstance(part["text"], str):
            return part["text"].strip()
        if "value" in part and isinstance(part["value"], str):
            return part["value"].strip()
    return ""


def _walk_text_documents(root: Path) -> Iterator[Tuple[str, str, str]]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if path.suffix.lower() not in {".json", ".txt", ".md", ".csv"}:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        yield (str(path.relative_to(root)), path.name, content)


def _format_timestamp(value: Optional[float]) -> str:
    if value in (None, ""):
        return ""
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return str(value)
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return dt.isoformat()
