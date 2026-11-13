"""Term-candidate pipeline: extract from test sessions -> review -> confirm -> rebuild snapshot.

The snapshot (persona context) is read-mostly; new slang met in conversation must not
silently rewrite it. This script keeps that loop explicit:

  extract    scan DSH sessions for query terms the model looked up, drop known ones,
             append new ones to qqbot-data/store/term_candidates.jsonl (status=pending)
  list       print pending candidates
  confirm    write the term into memory.db (term + term_sense, source_table=session:<id>)
             and mark the candidate confirmed
  reject     mark the candidate rejected (kept on record, never injected)
  rebuild    regenerate memory_snapshot.md (same builder the persona plugin reads)

Nothing here writes to the repo; all state lives under qqbot-data/store/.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT.parent / "qqbot-data"
DB = DATA / "store" / "memory.db"
CANDIDATES = DATA / "store" / "term_candidates.jsonl"
SNAPSHOT = DATA / "store" / "memory_snapshot.md"
SESSIONS = Path.home() / ".dsh" / "sessions" / "--home-dev-projects-qq-bot--"
TZ = timezone.utc

STOP = {
    "meme", "梗", "是什么", "是谁", "意思", "外号", "介绍", "最新", "版本", "怎么", "如何",
    "为什么", "什么", "吗", "的", "了", "是", "在", "和", "或", "与", "the", "a", "or", "and",
    "lookup", "search",
}


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def normalize(query: str) -> str:
    """Keep the leading content word of a lookup query; drop sentences and single chars."""
    text = re.sub(r"[^\w\u4e00-\u9fff]+", " ", query or "")
    parts = [p for p in text.split() if p and p.lower() not in STOP]
    if not parts:
        return ""
    word = parts[0]
    if len(word) < 2 or len(word) > 12:
        return ""
    if re.search(r"[我你他她它吗呢吧]", word):
        return ""
    return word


def read_session(path: Path) -> list[dict]:
    # Finished sessions are compressed; bothost's own harness home also has live, uncompressed ones.
    raw = subprocess.run(["zstd", "-dc", str(path)], capture_output=True, check=True).stdout if path.suffix == ".zstd" else path.read_bytes()
    return [json.loads(line) for line in raw.decode("utf-8", "replace").split("\n") if line.strip()]


def load_candidates() -> list[dict]:
    if not CANDIDATES.exists():
        return []
    return [json.loads(line) for line in CANDIDATES.read_text(encoding="utf-8").splitlines() if line.strip()]


def save_candidates(rows: list[dict]) -> None:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    CANDIDATES.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def known_terms() -> set[str]:
    known: set[str] = set()
    con = sqlite3.connect(DB)
    try:
        for (surface,) in con.execute("SELECT surface FROM term"):
            known.add(str(surface).strip())
    finally:
        con.close()
    if SNAPSHOT.exists():
        for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^- ([^：:]+)[：:]", line)
            if m:
                known.add(m.group(1).strip())
    for path in (DATA / "labels" / "term_refs.v1.json",):
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8")):
                known.add(str(row.get("term", "")).strip())
    return {k for k in known if k}


MEME_RE = re.compile(r"梗|meme|表情包|抽象|网络用语|流行|网红|二创|玩梗", re.I)


def session_results(records: list[dict]) -> dict[str, str]:
    """callId -> tool result text, so a search's own sources can justify the entry."""
    out: dict[str, str] = {}
    for record in records:
        if record.get("type") != "tool/result":
            continue
        message = (record.get("data") or {}).get("message") or {}
        call_id = str(message.get("toolCallId") or "")
        if not call_id:
            continue
        text = "".join(
            block.get("text", "") for block in (message.get("content") or []) if isinstance(block, dict)
        )
        out[call_id] = text
    return out


def result_meaning(text: str) -> str:
    """First source summary/title from a search_web result, compacted for the term table."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # bothost's search_web answers in plain lines: "1. title", url, date, summary.
        first = [x.strip() for x in text.split("\n2. ")[0].split("\n")]
        return (first[3] if len(first) > 3 and first[3] else first[0].removeprefix("1. "))[:120] if first[0].startswith("1. ") else ""
    if not isinstance(data, dict):
        return ""
    inner = data.get("text")
    if isinstance(inner, str):
        try:
            data = json.loads(inner)
        except json.JSONDecodeError:
            return ""
    sources = data.get("sources") or []
    if not sources or not isinstance(sources[0], dict):
        return ""
    first = sources[0]
    return str(first.get("summary") or first.get("title") or "").replace("\n", " ").strip()[:120]


def extract(paths: list[Path], auto_confirm: bool = True) -> dict:
    known = known_terms()
    rows = load_candidates()
    seen = {(r["term"], r["session"]) for r in rows}
    added = []
    for path in paths:
        session_id = path.parent.name
        try:
            records = read_session(path)
        except Exception as error:  # noqa: BLE001
            print(json.dumps({"skip": str(path), "error": str(error)}, ensure_ascii=False))
            continue
        results = session_results(records)
        for record in records:
            if record.get("type") != "tool/call":
                continue
            data = record.get("data") or {}
            name = str(data.get("name") or "").removeprefix("mcp__qq__")   # the same tools when they come from bothost
            if name not in ("search_web", "memory_search"):
                continue
            try:
                args = json.loads(data.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            query = str(args.get("query", "")).strip()
            term = normalize(query)
            if not term or len(term) > 24 or term in known:
                continue
            key = (term, session_id)
            if key in seen:
                continue
            seen.add(key)
            auto = False
            meaning = ""
            call_id = data.get("callId")
            result_text = results.get(call_id, "") if call_id else ""
            # A search that itself says it is a meme/slang skips the frequency gate and
            # goes straight into the term table (user decision, 2026-11-08).
            if auto_confirm and name == "search_web" and result_text and MEME_RE.search(result_text):
                meaning = result_meaning(result_text)
                if meaning:
                    write_term(term, meaning, "general", "general", f"search:{session_id}")
                    known.add(term)
                    auto = True
            row = {
                "term": term,
                "query": query,
                "session": session_id,
                "source": name,
                "found_at": now(),
                "status": "auto-confirmed" if auto else "pending",
                "meaning": meaning,
                "evidence": [f"session:{session_id}"] + ([f"search:{session_id}"] if auto else []),
            }
            rows.append(row)
            added.append(row)
    save_candidates(rows)
    return {
        "added": len(added),
        "auto_confirmed": sum(1 for r in added if r["status"] == "auto-confirmed"),
        "pending": sum(1 for r in rows if r["status"] == "pending"),
        "terms": [r["term"] for r in added],
    }


def write_term(term: str, meaning: str, chat: str, layer: str, source: str) -> None:
    """Write one confirmed term into memory.db (shared layer = chat code 'general')."""
    con = sqlite3.connect(DB)
    try:
        con.execute("INSERT OR IGNORE INTO chat(platform, code) VALUES ('qq', ?)", (chat,))
        chat_id = con.execute("SELECT id FROM chat WHERE code = ?", (chat,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO term(chat_id, surface) VALUES (?, ?)", (chat_id, term))
        term_id = con.execute("SELECT id FROM term WHERE chat_id = ? AND surface = ?", (chat_id, term)).fetchone()[0]
        con.execute(
            "INSERT OR REPLACE INTO term_sense(term_id, source_table, meaning, usage, confidence, learned_before, status) "
            "VALUES (?, ?, ?, '', ?, NULL, 'confirmed')",
            (term_id, source, meaning, layer),
        )
        if chat != "general":
            con.execute("INSERT OR IGNORE INTO chat(platform, code) VALUES ('qq', 'general')")
            general_id = con.execute("SELECT id FROM chat WHERE code = 'general'").fetchone()[0]
            con.execute("INSERT OR IGNORE INTO term(chat_id, surface) VALUES (?, ?)", (general_id, term))
            general_term = con.execute("SELECT id FROM term WHERE chat_id = ? AND surface = ?", (general_id, term)).fetchone()[0]
            con.execute(
                "INSERT OR REPLACE INTO term_sense(term_id, source_table, meaning, usage, confidence, learned_before, status) "
                "VALUES (?, ?, ?, '', ?, NULL, 'confirmed')",
                (general_term, source, meaning, layer),
            )
        con.commit()
    finally:
        con.close()


def confirm(term: str, meaning: str, chat: str, layer: str, session: str) -> dict:
    source = f"session:{session}" if session else "session"
    write_term(term, meaning, chat, layer, source)
    rows = load_candidates()
    for row in rows:
        if row["term"] == term and row["status"] == "pending":
            row["status"] = "confirmed"
            row["meaning"] = meaning
            row["confirmed_at"] = now()
    save_candidates(rows)
    return {"confirmed": term, "chat": chat, "layer": layer}


def rebuild() -> dict:
    result = subprocess.run(
        [str(ROOT.parent / "qqbot-data" / "venv" / "bin" / "python"), str(ROOT / "scripts" / "memory" / "build_snapshot.py")],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    ex = sub.add_parser("extract")
    ex.add_argument("--sessions", nargs="*", type=Path, help="session.v4.jsonl[.zstd] paths (default: all under the qq-bot session dir)")
    ex.add_argument("--session-root", type=Path, help="a harness sessions directory to scan instead, e.g. <bothost data_dir>/dsh-home/sessions")

    sub.add_parser("list")

    cf = sub.add_parser("confirm")
    cf.add_argument("--term", required=True)
    cf.add_argument("--meaning", required=True)
    cf.add_argument("--chat", default="general", help="group code, or 'general' for the shared layer")
    cf.add_argument("--layer", default="general", choices=("general", "local"))
    cf.add_argument("--session", default="")

    rj = sub.add_parser("reject")
    rj.add_argument("--term", required=True)

    rb = sub.add_parser("rebuild")

    args = ap.parse_args()
    if args.cmd == "extract":
        paths = args.sessions or (sorted(args.session_root.glob("*/*/session.v4.jsonl*")) if args.session_root
                                  else sorted(SESSIONS.glob("*/session.v4.jsonl.zstd")))
        print(json.dumps(extract(paths), ensure_ascii=False))
    elif args.cmd == "list":
        rows = [r for r in load_candidates() if r["status"] == "pending"]
        print(json.dumps(rows, ensure_ascii=False, indent=1))
    elif args.cmd == "confirm":
        print(json.dumps(confirm(args.term, args.meaning, args.chat, args.layer, args.session), ensure_ascii=False))
    elif args.cmd == "reject":
        rows = load_candidates()
        for row in rows:
            if row["term"] == args.term and row["status"] == "pending":
                row["status"] = "rejected"
                row["rejected_at"] = now()
        save_candidates(rows)
        print(json.dumps({"rejected": args.term}, ensure_ascii=False))
    else:
        print(json.dumps(rebuild(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
