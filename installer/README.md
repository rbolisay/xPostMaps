# TierMaps Windows Installer

Professional NSIS-based setup for **TierMaps 1.0** (fully self-contained; end users do not need Python).

## Prerequisites (build machine only)

- **Python 3.10+** (64-bit) on PATH — used to build the icon and verify dependencies
- **NSIS 3.x** with `makensis.exe` (default: `C:\Program Files (x86)\NSIS\`)
- Development venv created with `install.bat` and synced to `requirements.txt`

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

1. Verifies all required source assets exist (logos, coastlines JSON, app code)
2. Builds `TierMaps.ico` from `TierMaps.png` (used for setup wizard, Start Menu, and desktop shortcuts)
3. Syncs `venv` with `requirements.txt`
4. Copies application code, assets, default settings, and license into `installer\staging`
5. Downloads Windows **embeddable Python 3.13.7** and copies all runtime libraries from `venv` into `python\`
6. Runs `verify_staging.py` (file/package/DLL checks) and `preflight.py` (import + UI smoke test)
7. Compiles the NSIS script into a single setup executable

## What gets installed (everything is under the install folder)

| Location | Contents |
|----------|----------|
| `C:\Program Files\TierMaps\` | Application code, logos, launcher, license |
| `C:\Program Files\TierMaps\python\` | Embedded Python 3.13.7 + all libraries (PySide6, pyproj, numba, PyMuPDF, etc.) |
| `C:\Program Files\TierMaps\xpostmaps\assets\` | World coastlines and land polygons for minimap |
| `C:\Program Files\TierMaps\data\` | Default `settings.json`; user project databases created here |
| Start Menu → TierMaps | Launch shortcut, Uninstall shortcut |
| Optional | Desktop shortcut (checkbox on finish page) |
| Add/Remove Programs | TierMaps 1.0 entry with uninstaller |

No separate Python, Qt, PROJ, or VC++ installs are required on the target PC.

## Support troubleshooting

If TierMaps does not start after install:

1. Launch from **Start Menu → TierMaps** (not an old dev folder such as `C:\xPostMaps`)
2. Check `C:\Program Files\TierMaps\data\startup.log` for the exact error
3. Reinstall using the latest `TierMaps-1.0-Setup.exe`

## Version bump

Edit `!define APP_VERSION` in `TierMaps.nsi` and `__version__` in `xpostmaps/__init__.py`, then rebuild.

## Notes

- First build copies the full venv; expect a large installer (~230–250 MB).
- Sample navigation data is **not** bundled; users open their own project folders.
- User projects and databases live under `data\` in the install folder.
- Uninstall removes the entire install folder including user databases under `data\`.
- The desktop icon is derived from `TierMaps.png` at build time.
