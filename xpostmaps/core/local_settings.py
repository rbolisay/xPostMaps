"""Persist lightweight local UI settings."""

from __future__ import annotations

import json
from pathlib import Path

_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "data" / "settings.json"


def _read() -> dict:
    if not _SETTINGS_PATH.is_file():
        return {}
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_db_directory(default: Path) -> Path:
    raw = str(_read().get("db_directory", "")).strip()
    if raw and Path(raw).is_dir():
        return Path(raw)
    return default


def save_db_directory(directory: Path) -> None:
    data = _read()
    data["db_directory"] = str(directory)
    _write(data)
