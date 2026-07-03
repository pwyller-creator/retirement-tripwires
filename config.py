import configparser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_cfg = configparser.ConfigParser()
_cfg.read(ROOT / "config.ini")

FRED_API_KEY = _cfg.get("fred", "api_key", fallback="").strip()
SEC_USER_AGENT = _cfg.get("sec", "user_agent", fallback="RetirementTripwires contact@example.com").strip()

DATA_DIR = ROOT / _cfg.get("app", "data_dir", fallback="data")
STATE_DIR = DATA_DIR / "state"
LOG_DIR = ROOT / _cfg.get("app", "log_dir", fallback="logs")

DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

if not FRED_API_KEY:
    raise RuntimeError("FRED api_key is missing from config.ini -- fill in [fred] api_key.")
