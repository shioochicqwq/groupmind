"""Import the research files into the SQLite store and record every identifier change.

Two outputs, both outside the repository (they hold real message and sender ids):

- the database (schema in schema.sql);
- an id map file, one JSON line per object: {kind, chat, scope, old, new, extra}. It is the
  same as the id_map table, kept as a separate file so the mapping survives on its own.

`verify` rebuilds messages and colours from the database through the id map and checks that
they equal what the research code reads from the files, then that BM25 returns the same top
30 for every question. Experiments may only switch to the database after this passes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import time
from pathlib import Path

from bench import chunking, realdata
from bench.ledger import code_version
from bench.schema import Message, Visibility

SCHEMA = Path(__file__).with_name("schema.sql")
PLATFORM = "qq"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db)
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con


class Mapper:
    def __init__(self, con: sqlite3.Connection):
        self.con, self.rows = con, []

    def add(self, kind: str, chat: str, old: str, new: int, scope: str = "", extra: str = "") -> None:
        self.con.execute("INSERT OR REPLACE INTO id_map VALUES (?, ?, ?, ?, ?, ?)", (kind, chat, scope, old, new, extra))
        self.rows.append({"kind": kind, "chat": chat, "scope": scope, "old": old, "new": new, "extra": extra})


def import_group(con: sqlite3.Connection, mapper: Mapper, code: str, run_dir: Path) -> dict:
    """One group: chat, persons, messages, colour runs and colours, and term tables if any."""
    if realdata.splits().get(code) is not Visibility.DEV:
        raise SystemExit(f"{code} is not a DEV group; frozen groups are not imported during research")
    from bench.sanitize import Sanitizer

    messages = realdata.load_group(code)
    alias = Sanitizer(messages).alias
    con.execute("INSERT OR IGNORE INTO chat(platform, code) VALUES (?, ?)", (PLATFORM, code))
    chat_id = con.execute("SELECT id FROM chat WHERE code = ?", (code,)).fetchone()[0]
    mapper.add("chat", code, code, chat_id)

    person_of: dict[str, int] = {}
    for uid in dict.fromkeys(m.author for m in messages):
        con.execute("INSERT OR IGNORE INTO person(platform, platform_uid) VALUES (?, ?)", (PLATFORM, uid))
        person_of[uid] = con.execute("SELECT id FROM person WHERE platform = ? AND platform_uid = ?", (PLATFORM, uid)).fetchone()[0]
        mapper.add("person", code, uid, person_of[uid], extra=alias.get(uid, ""))

    source = f"{PLATFORM}:{code}"
    msg_of: dict[str, int] = {}
    names: dict[tuple[int, str], list] = {}
    for order, m in enumerate(messages):
        con.execute(
            "INSERT OR IGNORE INTO message(source, source_msg_id, chat_id, sender_id, ts, order_key, text, reply_to, media, nickname_at_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source, m.msg_id, chat_id, person_of[m.author], m.timestamp, order, m.content, m.reply_to,
             json.dumps(list(m.media)), m.nickname_at_time))
        mid = con.execute("SELECT id FROM message WHERE source = ? AND source_msg_id = ?", (source, m.msg_id)).fetchone()[0]
        msg_of[m.msg_id] = mid
        mapper.add("message", code, m.msg_id, mid)
        if m.nickname_at_time:
            key = (person_of[m.author], m.nickname_at_time)
            if key not in names:
                names[key] = [m.timestamp, m.timestamp, mid]
            names[key][1] = m.timestamp
    for (pid, name), (first, last, mid) in names.items():
        con.execute("INSERT OR REPLACE INTO person_name VALUES (?, ?, ?, ?, ?, ?)", (pid, chat_id, name, first, last, mid))

    stats = {"messages": len(messages), "persons": len(person_of), "names": len(names), "colors": 0, "unresolved_links": 0, "terms": 0}
    for path in sorted(run_dir.glob("colors.*.jsonl")):
        model = path.name[len("colors."):-len(".jsonl")]
        digest = sha256(path)
        con.execute("INSERT OR IGNORE INTO color_run(chat_id, model, source_file, source_sha256, batch_size, overlap) VALUES (?, ?, ?, ?, 150, 20)",
                    (chat_id, model, path.name, digest))
        run_id = con.execute("SELECT id FROM color_run WHERE chat_id = ? AND source_sha256 = ?", (chat_id, digest)).fetchone()[0]
        mapper.add("color_run", code, path.name, run_id, extra=digest)
        for seq, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
            c = json.loads(line)
            con.execute("INSERT OR IGNORE INTO color(run_id, seq, summary, labels) VALUES (?, ?, ?, ?)",
                        (run_id, seq, c.get("summary", ""), json.dumps(c.get("labels", []), ensure_ascii=False)))
            cid = con.execute("SELECT id FROM color WHERE run_id = ? AND seq = ?", (run_id, seq)).fetchone()[0]
            mapper.add("color", code, c["color_id"], cid, scope=path.name)
            for pos, old in enumerate(c["msg_ids"]):
                if old not in msg_of:
                    stats["unresolved_links"] += 1
                    continue
                con.execute("INSERT OR IGNORE INTO color_link VALUES (?, ?, ?)", (cid, msg_of[old], pos))
            stats["colors"] += 1

    tables = run_dir / "k_tables.json"
    if tables.exists():
        for table, entries in json.loads(tables.read_text(encoding="utf-8")).items():
            for e in entries:
                con.execute("INSERT OR IGNORE INTO term(chat_id, surface) VALUES (?, ?)", (chat_id, e["term"]))
                tid = con.execute("SELECT id FROM term WHERE chat_id = ? AND surface = ?", (chat_id, e["term"])).fetchone()[0]
                mapper.add("term", code, e["term"], tid)
                con.execute("INSERT OR IGNORE INTO term_sense(term_id, source_table, meaning, usage, confidence, learned_before) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (tid, table, e.get("meaning", ""), e.get("usage", ""), e.get("confidence", ""), e.get("learned_before")))
                sid = con.execute("SELECT id FROM term_sense WHERE term_id = ? AND source_table = ?", (tid, table)).fetchone()[0]
                mapper.add("term_sense", code, f"{table}:{e['term']}", sid, scope=table)
                stats["terms"] += 1
    return stats


# --- reading back -----------------------------------------------------------------------

def messages_from_db(con: sqlite3.Connection, code: str) -> list[Message]:
    rows = con.execute(
        "SELECT m.source_msg_id, p.platform_uid, m.ts, m.text, m.reply_to, m.media, m.nickname_at_time "
        "FROM message m JOIN chat c ON c.id = m.chat_id JOIN person p ON p.id = m.sender_id "
        "WHERE c.code = ? ORDER BY m.order_key", (code,)).fetchall()
    return [Message(msg_id=r[0], channel=code, author=r[1], timestamp=r[2], content=r[3], reply_to=r[4],
                    media=tuple(json.loads(r[5])), nickname_at_time=r[6]) for r in rows]


def colors_from_db(con: sqlite3.Connection, code: str, source_file: str) -> list[dict]:
    """Colour records in the research file format, with the old ids restored through id_map."""
    run = con.execute("SELECT r.id FROM color_run r JOIN chat c ON c.id = r.chat_id WHERE c.code = ? AND r.source_file = ?",
                      (code, source_file)).fetchone()[0]
    old_color = {new: old for old, new in con.execute(
        "SELECT old_id, new_id FROM id_map WHERE kind = 'color' AND chat_code = ? AND scope = ?", (code, source_file))}
    out = []
    for cid, summary, labels in con.execute("SELECT id, summary, labels FROM color WHERE run_id = ? ORDER BY seq", (run,)):
        ids = [r[0] for r in con.execute(
            "SELECT m.source_msg_id FROM color_link l JOIN message m ON m.id = l.message_id WHERE l.color_id = ? ORDER BY l.pos", (cid,))]
        out.append({"color_id": old_color[cid], "msg_ids": ids, "summary": summary, "labels": json.loads(labels)})
    return out


def verify(con: sqlite3.Connection, code: str, run_dir: Path, labels: Path | None) -> dict:
    """Messages, colours and BM25 rankings rebuilt from the database must equal the file-based ones."""
    file_msgs = realdata.load_group(code)
    db_msgs = messages_from_db(con, code)
    report = {"messages_equal": file_msgs == db_msgs, "messages": len(db_msgs)}
    for path in sorted(run_dir.glob("colors.*.jsonl")):
        file_colors = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
        # Links to messages missing from the export cannot be stored; compare what can be resolved.
        known = {m.msg_id for m in file_msgs}
        for c in file_colors:
            c["msg_ids"] = [i for i in c["msg_ids"] if i in known]
            c.setdefault("labels", [])
            c.setdefault("summary", "")
        report[f"colors_equal:{path.name}"] = file_colors == colors_from_db(con, code, path.name)

    # End to end on the retrieval layer: the research pipeline fed from the files vs from the database.
    from types import SimpleNamespace

    from bench.retrievers.bm25 import BM25
    from bench.run_abcd import prepare

    ctx = prepare(SimpleNamespace(group=code, out=run_dir, labels=labels, extra_segments=220, absent=150, workers=8, budget=1500))
    colors_db = colors_from_db(con, code, "colors.gemini-3.8-flash-high.jsonl")
    from bench.run_s0 import sanitized
    from bench.sanitize import Sanitizer
    from bench.tasks.real_tasks import clean_messages

    msgs_db = sanitized(clean_messages(db_msgs), Sanitizer(db_msgs))
    same = 0
    for kind, file_index in (("summary", ctx.summary_index), ("raw", ctx.raw_index)):
        db_index = BM25(chunking.from_colors(msgs_db, colors_db, kind), ctx.tok)
        agree = sum([b.block_id for b, _ in file_index.search(q["question"], ctx.end_ts, 30, ctx.channel)]
                    == [b.block_id for b, _ in db_index.search(q["question"], ctx.end_ts, 30, ctx.channel)]
                    for q in ctx.questions)
        report[f"bm25_top30_equal:{kind}"] = f"{agree}/{len(ctx.questions)}"
        same += agree == len(ctx.questions)
    report["passed"] = bool(report["messages_equal"] and all(v for k, v in report.items() if k.startswith("colors_equal"))
                            and same == 2)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("import", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--db", type=Path, required=True)
        p.add_argument("--groups", nargs="+", required=True, help="code=run folder, e.g. 4fe395=runs/real-dev")
        p.add_argument("--labels", type=Path, help="merged labels for the DEV-1 questions")
        p.add_argument("--labels-group", default="4fe395")
    sub.choices["import"].add_argument("--map", type=Path, required=True)
    args = ap.parse_args()
    groups = dict(g.split("=", 1) for g in args.groups)
    con = connect(args.db)
    if args.cmd == "import":
        mapper = Mapper(con)
        stats, inputs = {}, {}
        for code, folder in groups.items():
            stats[code] = import_group(con, mapper, code, Path(folder))
            for p in sorted(Path(folder).glob("colors.*.jsonl")) + [Path(folder) / "k_tables.json"]:
                if p.exists():
                    inputs[str(p.name) + "@" + code] = sha256(p)
        con.execute("INSERT INTO migration(at, code_version, inputs) VALUES (?, ?, ?)",
                    (time.strftime("%Y-%m-%d %H:%M"), json.dumps(code_version()), json.dumps(inputs)))
        con.commit()
        args.map.parent.mkdir(parents=True, exist_ok=True)
        with args.map.open("w", encoding="utf-8") as f:
            for r in mapper.rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(json.dumps({"stats": stats, "id_map_rows": len(mapper.rows)}, ensure_ascii=False))
        return 0
    results = {code: verify(con, code, Path(folder), args.labels if code == args.labels_group else None)
               for code, folder in groups.items()}
    con.execute("UPDATE migration SET verified = ? WHERE id = (SELECT max(id) FROM migration)", (json.dumps(results),))
    con.commit()
    print(json.dumps(results, ensure_ascii=False))
    return 0 if all(r["passed"] for r in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
