# TierMaps Windows Installer

Professional NSIS-based setup for TierMaps (self-contained; end users do not need Python).

## Prerequisites (build machine only)

- **Python 3.10+** (64-bit) on PATH
- **NSIS 3.x** with `makensis.exe` (default: `C:\Program Files (x86)\NSIS\`)
- Internet access during build (pip downloads dependencies)

## Build

From the repository root:

```bat
installer\build_installer.bat
```

Output:

```text
dist\TierMaps-0.1.0-Setup.exe
```

The build script:

1. Copies `xpostmaps`, `run.py`, and `requirements.txt` into `installer\staging`
2. Creates a virtual environment and installs dependencies into staging
3. Compiles the NSIS script into a single setup executable

## What gets installed

| Location | Contents |
|----------|----------|
| `C:\Program Files\TierMaps\` | Application code, embedded `venv`, launcher |
| Start Menu → TierMaps | Launch shortcut, Uninstall shortcut |
| Optional | Desktop shortcut (checkbox on finish page) |
| Add/Remove Programs | TierMaps entry with uninstaller |

## Version bump

Edit `!define APP_VERSION` in `TierMaps.nsi` and `__version__` in `xpostmaps/__init__.py`, then rebuild.

## Notes

- First build downloads PySide6 and other wheels; expect a large installer (~300–500 MB).
- Sample data (`Sample Navplan`, `Imports`) is **not** bundled.
- User projects and databases live under `data\` in the install folder (created empty at install).
