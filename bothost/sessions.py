"""One-on-one conversations held in harness sessions, copied from the harness's session logs into the store.

A session started from a given preset is a private chat with the bot. Its user lines and the bot's replies are
recorded as one chat of the store, so a new session can recall what was said in earlier ones. Tool calls,
reasoning and the lines plugins add are left out. Copying again adds only what is new.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .store import Store

CODE = "dm"   # the chat these conversations are stored under; the group bot never recalls it
_seen: dict[Path, tuple[int, int]] = {}   # log file -> (mtime, size) when last read
_done: dict[str, int] = {}                # session id -> last event number copied
_latest: tuple[float, str] = (0.0, "")    # time and session of the newest line


def _events(path: Path, preset: str) -> list[dict]:
    """The events of a log, or nothing when its session is of another preset (known from the first line, so the rest is not read)."""
    with subprocess.Popen(["zstd", "-dc", str(path)] if path.suffix == ".zstd" else ["cat", str(path)], stdout=subprocess.PIPE) as p:
        out = []
        for row in p.stdout:
            try:
                out.append(json.loads(row))
            except ValueError:   # a line still being written
                break
            if len(out) == 1 and out[0].get("agentPreset") != preset:
                p.kill()
                return []
        return out


def _text(parts: list[dict]) -> str:
    return "\n".join(p.get("text", "").strip() if p.get("type") == "text" else "[图片]" for p in parts if p.get("type") in ("text", "image")).strip()


def sync(store: Store, root: Path, preset: str, code: str, names: tuple[str, str] = ("对方", "我")) -> str:
    """Copy new lines of the preset's sessions into chat `code`. Returns the id of the session written to last (the caller's, most likely)."""
    global _latest
    new = []
    for path in sorted(Path(root).glob("*/*/session.v4.jsonl*")):
        st = path.stat()
        if _seen.get(path) == (st.st_mtime_ns, st.st_size):
            continue
        _seen[path] = (st.st_mtime_ns, st.st_size)
        events = _events(path, preset)
        if not events:
            continue
        sid = events[0]["id"]
        for e in events:
            data, seq = e.get("data") or {}, e.get("seq", 0)
            if e.get("type") == "user/message" and (data.get("source") or {}).get("kind") == "user":
                who, text = 0, _text(data.get("content") or [])
            elif e.get("type") == "assistant/message":
                who, text = 1, _text([p for p in (data.get("message") or {}).get("content") or [] if p.get("type") == "text"])
            else:
                continue
            ts = e.get("time", 0) / 1000
            _latest = max(_latest, (ts, sid))
            if text and seq > _done.get(sid, -1):
                new.append((ts, sid, seq, who, text))
    for ts, sid, seq, who, text in sorted(new):   # the store numbers lines as they come
        store.add(code, f"{sid}:{seq}", ts, f"{code}:{('user', 'bot')[who]}", names[who], text)
        _done[sid] = max(_done.get(sid, -1), seq)
    return _latest[1]
