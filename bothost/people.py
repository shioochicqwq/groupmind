"""People the bot gets to know by itself: who is who, a nickname, a one-line impression and its attitude.

Learned in three places, none of which costs a model call of its own:
- the bot calls the `note_person` tool when it notices something in the chat;
- the note it writes when its context is compacted may end with a 【人物】 section (deploy/dsh/compaction-persona.md);
- a background task's account may carry a "people" list (bothost/handoff.py).

Kept in `person_fact` (bench/store/schema.sql), append-only: a newer impression or attitude replaces the older one by
pointing to it, nicknames accumulate, undoing only marks a row. Attitude and impression belong to the person, so they
are shared across groups. Display names are not learned: the store already records every name an account was shown
under (`person_name`), so "who is who" between a display name and a person is read from there.

The model sees this as a people section in the system prompt, built when the process starts, and, for what is learned
later, a block appended at the start of the next turn between 【人物表追加】 markers; `who_is` looks a person up.

    python -m bothost.people history --db memory.db [--name 显示名]
    python -m bothost.people undo --db memory.db ID
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import time
from collections.abc import Iterable

KINDS = ("alias", "impression", "attitude", "same_as")
REPLACED = ("impression", "attitude")       # one current value; a new one replaces it
LINE = re.compile(r"^\s*[-*•]?\s*(?P<name>[^｜|\n]+?)\s*[｜|](?P<rest>.+)$")
FIELD = {"外号": "alias", "印象": "impression", "态度": "attitude", "同一个人": "same_as"}
OPEN, CLOSE = "【人物表追加】", "【/人物表追加】"


def clean_name(name: str) -> str:
    """A display name without a QQ number some carry, e.g. '阿青(12345678)'."""
    return re.sub(r"[（(]\s*\d{5,}\s*[)）]|\d{5,}", "", name or "").strip()


def _chat(db: sqlite3.Connection, code: str) -> int | None:
    row = db.execute("SELECT id FROM chat WHERE code = ?", (code,)).fetchone() if code else None
    return row[0] if row else None


def resolve(db: sqlite3.Connection, name: str, code: str = "") -> list[int]:
    """Persons a name may mean, most likely first: the name as shown in this chat (newest use first), then a nickname
    learned before, then the name as shown in any chat."""
    name = clean_name(name)
    if not name:
        return []
    chat = _chat(db, code)
    found: list[int] = []

    def take(rows: Iterable) -> None:
        for (pid,) in rows:
            if pid not in found:
                found.append(pid)
    if chat is not None:
        take(db.execute("SELECT person_id FROM person_name WHERE chat_id = ? AND name = ? ORDER BY last_seen DESC", (chat, name)))
        if not found:   # the same name with a number in it, as some display names carry
            take([(p,) for p, n in db.execute("SELECT person_id, name FROM person_name WHERE chat_id = ? ORDER BY last_seen DESC", (chat,))
                  if clean_name(n) == name])
    take(db.execute("SELECT person_id FROM person_fact WHERE kind = 'alias' AND value = ? AND undone = 0 ORDER BY at DESC", (name,)))
    if not found:
        take(db.execute("SELECT person_id FROM person_name WHERE name = ? ORDER BY last_seen DESC", (name,)))
    return found


def add(db: sqlite3.Connection, person: int, kind: str, value: str, source: str, code: str = "", evidence: str = "") -> int | None:
    """Record one fact. None when it says nothing new (the same nickname again, the same impression)."""
    value = value.strip()[:200]
    if kind not in KINDS or not value:
        return None
    current = current_facts(db, person)
    if kind in REPLACED and current.get(kind) == value or kind in ("alias", "same_as") and value in current.get(kind + "es", []):
        return None
    with db:
        fid = db.execute("INSERT INTO person_fact(person_id, kind, value, source, chat_id, evidence, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (person, kind, value, source, _chat(db, code), evidence[:500], time.time())).lastrowid
        if kind in REPLACED:
            db.execute("UPDATE person_fact SET replaced_by = ? WHERE person_id = ? AND kind = ? AND id != ? AND replaced_by IS NULL AND undone = 0",
                       (fid, person, kind, fid))
    return fid


def undo(db: sqlite3.Connection, fid: int) -> bool:
    """Take a fact back; an impression or attitude it had replaced becomes current again."""
    with db:
        n = db.execute("UPDATE person_fact SET undone = 1 WHERE id = ? AND undone = 0", (fid,)).rowcount
        db.execute("UPDATE person_fact SET replaced_by = NULL WHERE replaced_by = ?", (fid,))
    return bool(n)


def current_facts(db: sqlite3.Connection, person: int) -> dict:
    out: dict = {"aliases": [], "same_ases": []}
    for kind, value in db.execute("SELECT kind, value FROM person_fact WHERE person_id = ? AND undone = 0 AND replaced_by IS NULL ORDER BY at",
                                  (person,)):
        if kind == "alias":
            out["aliases"].append(value)
        elif kind == "same_as":
            out["same_ases"].append(value)
        else:
            out[kind] = value
    return out


def shown_as(db: sqlite3.Connection, person: int, top: int = 3) -> list[str]:
    """The names this person was shown under lately, most recent use first."""
    out: list[str] = []
    for (name,) in db.execute("SELECT name FROM person_name WHERE person_id = ? ORDER BY last_seen DESC", (person,)):
        n = clean_name(name)
        if n and n not in out:
            out.append(n)
    return out[:top]


def entry(db: sqlite3.Connection, person: int) -> str:
    facts, names = current_facts(db, person), shown_as(db, person)
    parts = [f"群里显示为：{'、'.join(names) or '（不明）'}"]
    if facts["aliases"]:
        parts.append(f"外号：{'、'.join(facts['aliases'])}")
    if facts["same_ases"]:
        parts.append(f"同一个人：{'、'.join(facts['same_ases'])}")
    for key, label in (("impression", "印象"), ("attitude", "你的态度")):
        if facts.get(key):
            parts.append(f"{label}：{facts[key]}")
    return "- " + "；".join(parts)


def learned_section(db: sqlite3.Connection) -> str:
    """Everyone the bot has learned something about, for the system prompt at start."""
    persons = [p for (p,) in db.execute("SELECT person_id FROM person_fact WHERE undone = 0 GROUP BY person_id ORDER BY max(at)")]
    if not persons:
        return ""
    return ("## 后来认识的人（你自己记下的，比上面的新）\n"
            + "\n".join(entry(db, p) for p in persons))


def changed_since(db: sqlite3.Connection, after: int) -> tuple[list[str], int]:
    """Entries of the persons with facts recorded after fact id `after`, and the newest id. For the turn-tail block."""
    rows = db.execute("SELECT id, person_id FROM person_fact WHERE id > ? ORDER BY id", (after,)).fetchall()
    persons = list(dict.fromkeys(p for _, p in rows))
    return [entry(db, p) for p in persons], max([after, *(i for i, _ in rows)])


def block(entries: list[str]) -> str:
    return f"{OPEN}（你新记下的人，不是群消息）\n" + "\n".join(entries) + f"\n{CLOSE}" if entries else ""


def latest_id(db: sqlite3.Connection) -> int:
    return db.execute("SELECT coalesce(max(id), 0) FROM person_fact").fetchone()[0]


def parse_section(text: str) -> list[dict]:
    """People lines from a 【人物】 section of a note: `显示名｜外号：…｜印象：…｜态度：…`, any field may be left out."""
    m = re.search(r"【人物】(.*?)(?:\n\s*【|\Z)", text or "", re.S)
    out = []
    for raw in (m.group(1).splitlines() if m else []):
        lm = LINE.match(raw)
        if not lm:
            continue
        row = {"name": lm.group("name").strip()}
        for part in re.split(r"[｜|]", lm.group("rest")):
            key, _, value = part.partition("：") if "：" in part else part.partition(":")
            if FIELD.get(key.strip()) and value.strip() and value.strip() not in ("无", "-", "—"):
                row[FIELD[key.strip()]] = value.strip()
        if len(row) > 1:
            out.append(row)
    return out


def apply(db: sqlite3.Connection, updates: Iterable[dict], source: str, code: str = "", evidence: str = "") -> dict:
    """Record a list of {name, alias?, impression?, attitude?, same_as?}. Names that match nobody, or more than one
    person equally, are skipped and counted, never guessed."""
    done = {"recorded": 0, "unknown": [], "ambiguous": []}
    for u in updates:
        name = str(u.get("name", "")).strip()
        persons = resolve(db, name, code)
        if not persons:
            done["unknown"].append(name)
            continue
        for kind in KINDS:
            for value in ([u[kind]] if isinstance(u.get(kind), str) else u.get(kind) or []):
                if add(db, persons[0], kind, str(value), source, code, evidence):
                    done["recorded"] += 1
    return done


def main() -> int:
    ap = argparse.ArgumentParser(description="See or undo what the bot learned about people.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("history")
    h.add_argument("--db", required=True)
    h.add_argument("--name", default="")
    u = sub.add_parser("undo")
    u.add_argument("--db", required=True)
    u.add_argument("id", type=int)
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    if args.cmd == "undo":
        print("undone" if undo(db, args.id) else "nothing to undo")
        return 0
    persons = resolve(db, args.name) if args.name else None
    sql = "SELECT id, person_id, kind, value, source, datetime(at, 'unixepoch', '+8 hours'), replaced_by, undone FROM person_fact"
    rows = db.execute(sql + (f" WHERE person_id IN ({','.join('?' * len(persons))})" if persons else "") + " ORDER BY id", persons or ()).fetchall()
    for fid, pid, kind, value, source, at, repl, und in rows:
        state = "撤销" if und else f"被 #{repl} 替换" if repl else "当前"
        print(f"#{fid} [{at}] {'、'.join(shown_as(db, pid, 1)) or pid} {kind}={value} ({source}, {state})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
