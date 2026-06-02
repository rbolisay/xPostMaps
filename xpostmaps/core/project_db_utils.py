"""Project name ↔ database file path helpers."""

from __future__ import annotations

import re
from pathlib import Path

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_project_db_stem(name: str) -> str:
    """Build a safe filename stem from a project name."""
    stem = _INVALID_FILENAME_CHARS.sub("_", name.strip())
    stem = stem.strip("._ ")
    return stem or "project"


def project_db_path(directory: Path, project_name: str) -> Path:
    """Return the SQLite file path for a named project (TierSeis-style one project per file)."""
    return directory / f"{sanitize_project_db_stem(project_name)}.db"
