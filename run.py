"""Launch TierMaps."""

from __future__ import annotations

import os
import sys
from multiprocessing import freeze_support

# Installed shortcuts may start pythonw without setting the working directory.
_APP_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(_APP_ROOT)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

from xpostmaps.main import main

if __name__ == "__main__":
    freeze_support()
    raise SystemExit(main())
