from __future__ import annotations
import hashlib, hmac, json, os, secrets, subprocess, urllib.request
from pathlib import Path
from typing import Any

APP_VERSION = "0.1.0"
BASE_PATH = os.getenv("OOFM_BASE_PATH", "/font-manager").rstrip("/")
BIND_HOST = os.getenv("OOFM_BIND_HOST", "0.0.0.0")
PORT = int(os.getenv("OOFM_PORT", "8777"))
STATE_DIR = Path(os.getenv("OOFM_STATE_DIR", "/var/lib/onlyoffice-font-manager"))
MANAGED_DIR = STATE_DIR / "managed"
CACHE_DIR = STATE_DIR / "cache"
LOCAL_DIR = STATE_DIR / "local"
CONFIG_FILE = Path(os.getenv("OOFM_CONFIG", "/etc/onlyoffice-font-manager.json"))
FONTSOURCE_API = "https://api.fontsource.org/v1"
NOTO_COLOR_EMOJI = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/2D/fonts/NotoColorEmoji.ttf"
MAX_UPLOAD = 40 * 1024 * 1024
CATALOG_TTL = 6 * 3600
DETAIL_TTL = 24 * 3600

COMM_CKROOT = "/var/www/onlyoffice/WebStudio/UserControls/Common/ckeditor"
COMM_CFG = f"{COMM_CKROOT}/config.js"
COMM_WEBROOT = f"{COMM_CKROOT}/onlyoffice-font-manager"
COMM_WEBFONTS = f"{COMM_WEBROOT}/fonts"
COMM_CSS = f"{COMM_WEBROOT}/fonts.css"
COMM_PLUGIN_DIR = f"{COMM_CKROOT}/plugins/ooemoji"
DOC_DEST = "/usr/share/fonts/truetype/custom/onlyoffice-font-manager"

for d in (STATE_DIR, MANAGED_DIR, CACHE_DIR, LOCAL_DIR):
    d.mkdir(parents=True, exist_ok=True)

def load_config() -> dict[str, Any]:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {
        "admin_password": os.getenv("OOFM_ADMIN_PASSWORD", "change-me"),
        "proxy_secret": os.getenv("OOFM_PROXY_SECRET", "development"),
        "session_secret": os.getenv("OOFM_SESSION_SECRET", secrets.token_hex(32)),
    }

CONFIG = load_config()

def sh(args: list[str], *, check: bool = True, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=check, capture_output=True, text=text)

def fetch_bytes(url: str, timeout: int = 45) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": f"onlyoffice-font-manager/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()

def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)

def session_value() -> str:
    key = str(CONFIG.get("session_secret", "development")).encode()
    return hmac.new(key, b"admin", hashlib.sha256).hexdigest()

def csrf_value() -> str:
    key = str(CONFIG.get("session_secret", "development")).encode()
    return hmac.new(key, b"csrf", hashlib.sha256).hexdigest()
