"""Fast SQLite database file listing for the project browser."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_SUFFIXES = (".db", ".sqlite")


def format_file_size(num_bytes: int | float | None) -> str:
    try:
        size = float(num_bytes or 0)
    except (TypeError, ValueError):
        size = 0.0
    units = ("B", "KB", "MB", "GB")
    unit = units[0]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} B"
    return f"{size:.1f} {unit}"


def _parse_iso_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        text = value.strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _collect_db_files(directory: Path) -> list[Path]:
    files: list[Path] = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return files
    for entry in entries:
        if entry.is_file() and entry.name.lower().endswith(_DB_SUFFIXES):
            files.append(Path(entry.path))
    return sorted(files, key=lambda path: path.name.lower())


def _project_count(db_path: Path) -> int:
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='projects'"
        ).fetchone()
        if not row or int(row[0]) == 0:
            conn.close()
            return 0
        count_row = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        conn.close()
        return int(count_row[0]) if count_row else 0
    except (OSError, sqlite3.Error):
        return 0


def sqlite_database_rows(directory: str | Path) -> list[dict]:
    """Return metadata for .db / .sqlite files without QFileDialog's slow model."""
    rows: list[dict] = []
    folder = Path(directory) if directory else Path()
    if not folder.is_dir():
        return rows

    for db_path in _collect_db_files(folder):
        try:
            stat = db_path.stat()
            rows.append(
                {
                    "name": db_path.name,
                    "path": str(db_path.resolve()),
                    "size": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                    "projects": _project_count(db_path),
                }
            )
        except OSError:
            continue
    return rows


def sqlite_project_rows(directory: str | Path) -> list[dict]:
    """Return one row per saved project across all database files in a folder."""
    rows: list[dict] = []
    folder = Path(directory) if directory else Path()
    if not folder.is_dir():
        return rows

    for db_path in _collect_db_files(folder):
        try:
            stat = db_path.stat()
            conn = sqlite3.connect(str(db_path))
            table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='projects'"
            ).fetchone()
            if not table:
                conn.close()
                continue
            for name, updated_at in conn.execute(
                "SELECT name, updated_at FROM projects ORDER BY updated_at DESC"
            ):
                project_name = str(name or "").strip()
                if not project_name:
                    continue
                updated_ts = _parse_iso_timestamp(str(updated_at or ""))
                rows.append(
                    {
                        "project_name": project_name,
                        "database": db_path.name,
                        "path": str(db_path.resolve()),
                        "size": int(stat.st_size),
                        "mtime": updated_ts if updated_ts is not None else float(stat.st_mtime),
                        "updated_at": str(updated_at or ""),
                    }
                )
            conn.close()
        except (OSError, sqlite3.Error):
            continue

    rows.sort(
        key=lambda item: (
            float(item.get("mtime") or 0),
            str(item.get("project_name") or "").lower(),
        ),
        reverse=True,
    )
    return rows


def format_mtime(epoch: float) -> str:
    try:
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return ""
