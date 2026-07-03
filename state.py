import json
from config import STATE_DIR

_MISSING = object()


def load(name, default=_MISSING):
    path = STATE_DIR / f"{name}.json"
    if not path.exists():
        return {} if default is _MISSING else default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(name, data):
    path = STATE_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
