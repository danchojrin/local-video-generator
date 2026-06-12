"""
Gestión de configuraciones guardadas e historial de videos.
"""

import json
from datetime import datetime
from pathlib import Path

STORE = Path.home() / ".pv_videogen"
CONFIGS_DIR  = STORE / "configs"
HISTORY_FILE = STORE / "history.json"
MAX_HISTORY  = 20


def _ensure():
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)


def save_config(name: str, settings: dict) -> None:
    _ensure()
    data = {"name": name, "saved_at": datetime.now().isoformat(), "settings": settings}
    (CONFIGS_DIR / f"{name}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_config(name: str) -> dict:
    path = CONFIGS_DIR / f"{name}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("settings", {})


def list_configs() -> list:
    _ensure()
    out = []
    for p in sorted(CONFIGS_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            out.append({"name": d.get("name", p.stem), "saved_at": d.get("saved_at", ""), "stem": p.stem})
        except Exception:
            pass
    return out


def delete_config(name: str) -> None:
    (CONFIGS_DIR / f"{name}.json").unlink(missing_ok=True)


def add_to_history(entry: dict) -> None:
    _ensure()
    history = load_history()
    history.insert(0, {**entry, "timestamp": datetime.now().isoformat()})
    HISTORY_FILE.write_text(
        json.dumps(history[:MAX_HISTORY], indent=2, ensure_ascii=False), encoding="utf-8"
    )


def load_history() -> list:
    _ensure()
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []
