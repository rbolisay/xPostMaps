"""Application display names and credits."""

from pathlib import Path
from urllib.parse import quote

APP_NAME = "TierMaps"
APP_SUBTITLE = "Navigation PostMaps Viewer"
APP_WINDOW_TITLE = f"{APP_NAME} — {APP_SUBTITLE}"

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_LOGO_PATH = _PROJECT_ROOT / "TierMaps_No_bg.png"

SUPPORT_EMAIL = "rbolisay416@gmail.com"
SUPPORT_MAILTO = f"mailto:{SUPPORT_EMAIL}?subject={quote('TierMaps Bug Report')}"
DEVELOPER_CREDIT = "Developed by R. Bolisay"
DEVELOPER_CREDIT_HTML = (
    f"Developed by R. Bolisay · Report issues: "
    f'<a href="{SUPPORT_MAILTO}">{SUPPORT_EMAIL}</a>'
)
