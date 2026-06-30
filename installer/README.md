# TierMaps Windows Installer

Professional NSIS-based setup for **TierMaps 1.0** (self-contained; end users do not need Python).

## Prerequisites (build machine only)

- **Python 3.10+** (64-bit) on PATH — used to build the icon and verify dependencies
- **NSIS 3.x** with `makensis.exe` (default: `C:\Program Files (x86)\NSIS\`)
- Internet access during build (pip downloads dependency wheels into the bundled runtime)

## Build

From the repository root:

```bat
installer\build_installer.bat
```

Output:

```text
dist\TierMaps-1.0-Setup.exe
```

The build script:

1. Builds `TierMaps.ico` from `TierMaps.png` (used for setup wizard, Start Menu, and desktop shortcuts)
2. Copies `xpostmaps`, `run.py`, and `requirements.txt` into `installer\staging`
3. Downloads Windows **embeddable Python** and installs all `requirements.txt` packages into a portable `python\` folder (relocatable — works in `Program Files` on any PC)
4. Verifies imports and runs an off-screen smoke test
5. Compiles the NSIS script into a single setup executable

## What gets installed

| Location | Contents |
|----------|----------|
| `C:\Program Files\TierMaps\` | Application code, bundled Python runtime + libraries, launcher |
| Start Menu → TierMaps | Launch shortcut, Uninstall shortcut |
| Optional | Desktop shortcut (checkbox on finish page) |
| Add/Remove Programs | TierMaps 1.0 entry with uninstaller |

## Version bump

Edit `!define APP_VERSION` in `TierMaps.nsi` and `__version__` in `xpostmaps/__init__.py`, then rebuild.

## Notes

- First build downloads PySide6 and other wheels; expect a large installer (~300–500 MB).
- Sample data (`Sample Navplan`, `Imports`) is **not** bundled.
- User projects and databases live under `data\` in the install folder (created empty at install).
- The desktop icon is derived from `TierMaps.png` at build time.
