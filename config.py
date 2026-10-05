import configparser
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_cfg = configparser.ConfigParser()
_cfg.read(ROOT / "config.ini")

# The FRED key lives outside the OneDrive-synced project folder so it never
# syncs; config.ini's [fred] api_key is only a fallback for older setups.
FRED_KEY_FILE = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "fallout76er-tools" / "fred-api-key.txt"


def _load_fred_key():
    try:
        key = FRED_KEY_FILE.read_text(encoding="utf-8-sig").strip()
        if key:
            return key
    except OSError:
        pass
    return _cfg.get("fred", "api_key", fallback="").strip()


FRED_API_KEY = _load_fred_key()
SEC_USER_AGENT = _cfg.get("sec", "user_agent", fallback="RetirementTripwires contact@example.com").strip()

_SECRET_RE = re.compile(r"(api_key=)[^&\s\"']+", re.IGNORECASE)


def redact(text):
    """Scrub the FRED API key from text bound for logs/console.

    requests puts the full request URL (query string included) in HTTP error
    messages, so a 5xx from FRED would otherwise write the key into logs/.
    """
    text = _SECRET_RE.sub(r"\1REDACTED", str(text))
    if FRED_API_KEY:
        text = text.replace(FRED_API_KEY, "REDACTED")
    return text


DATA_DIR = ROOT / _cfg.get("app", "data_dir", fallback="data")
STATE_DIR = DATA_DIR / "state"
LOG_DIR = ROOT / _cfg.get("app", "log_dir", fallback="logs")

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

if not FRED_API_KEY:
    raise RuntimeError(f"FRED api_key is missing -- save it to {FRED_KEY_FILE} (or fill in [fred] api_key in config.ini).")
