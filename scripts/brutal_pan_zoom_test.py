"""Brutal pan/zoom stress test — delegates to real 7027.db benchmark when available."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.brutal_7027_test import main as run_7027_main


def main() -> None:
    db_path = ROOT / "data" / "7027.db"
    if db_path.is_file():
        run_7027_main()
        return
    print("7027.db not found at data/7027.db — run brutal_7027_test.py with your database path.")


if __name__ == "__main__":
    main()
