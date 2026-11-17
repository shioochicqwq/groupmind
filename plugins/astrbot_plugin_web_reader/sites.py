"""Per-site knowledge: the defaults shipped in sites.json plus what a running reader learned, kept in a file of its own."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from urllib.parse import urlsplit

DEFAULTS = Path(__file__).with_name("sites.json")
_lock = threading.Lock()


def host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Sites:
    """kind -> hosts; also hints per site for a model reading it (defaults only). `learned` is the file new entries go to; empty keeps them in memory only."""

    def __init__(self, learned: str | os.PathLike = "") -> None:
        self.learned = Path(learned) if learned else None
        self.known: dict[str, set[str]] = {}
        self.hints: dict[str, dict] = _read(DEFAULTS).get("notes", {}).get("sites", {})
        for src in (_read(DEFAULTS), _read(self.learned) if self.learned else {}):
            for kind, v in src.items():
                if isinstance(v, dict) and "hosts" in v:
                    self.known.setdefault(kind, set()).update(v.get("hosts") or [])

    def has(self, kind: str, url_or_host: str) -> bool:
        h = host(url_or_host) if "://" in url_or_host else url_or_host
        return h in self.known.get(kind, set())

    def add(self, kind: str, url_or_host: str) -> None:
        h = host(url_or_host) if "://" in url_or_host else url_or_host
        if not h or self.has(kind, h):
            return
        self.known.setdefault(kind, set()).add(h)
        if self.learned is None:
            return
        with _lock:
            data = _read(self.learned)
            entry = data.setdefault(kind, {"hosts": []})
            entry["hosts"] = sorted(set(entry.get("hosts") or []) | {h})
            self.learned.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.learned.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.learned)

    def notes(self, text: str) -> dict[str, list[str]]:
        """Hints for the sites a text names (by host or by what people call them): host -> lines."""
        low = text.lower()
        return {h: v.get("notes") or [] for h, v in self.hints.items()
                if h in low or any(n in low for n in v.get("names") or [])}
