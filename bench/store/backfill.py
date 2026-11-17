"""Add later messages of a group to the store from a newer ChatLab JSONL export (the same format as the research files).

Messages are matched by their QQ message id, which the earlier import kept, so only messages the store does not
have yet are added, wherever the two exports overlap. Senders map to the persons already there by their uid.

Nothing is added to id_map: the frozen retrieval (bench/store/frozen.py) is built from the messages id_map lists,
so it stays exactly as it was. The new messages are searched like messages the bot recorded live (keyword index,
after the last coloured message). FROZEN groups are refused, and only the codes given are taken.

    python -m bench.store.backfill --db memory.db --exports DIR --codes ed14b7,4fe395   # DIR holds <group number>.jsonl

FROZEN codes come from the research selection (selection.json) when it is there; where it is not (a deploy machine),
they have to be given with --frozen-codes, and the run refuses to start without either.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

from bench.datasets import qq_export
from bothost.store import Store

PLATFORM = "qq"


def code_of(number: str) -> str:
    return hashlib.sha256(number.encode()).hexdigest()[:6]


def backfill(store: Store, path: Path, code: str) -> dict:
    con = store.db
    messages = qq_export.load(path, code)
    source = f"{PLATFORM}:{code}"
    with con:
        con.execute("INSERT OR IGNORE INTO chat(platform, code) VALUES (?, ?)", (PLATFORM, code))
        chat = con.execute("SELECT id FROM chat WHERE code = ?", (code,)).fetchone()[0]
        have = {r[0] for r in con.execute("SELECT source_msg_id FROM message WHERE source = ?", (source,))}
        order = con.execute("SELECT coalesce(max(order_key), -1) + 1 FROM message WHERE chat_id = ?", (chat,)).fetchone()[0]
        added, first, last, persons = 0, None, None, set()
        for m in messages:
            if m.msg_id in have:
                continue
            con.execute("INSERT OR IGNORE INTO person(platform, platform_uid) VALUES (?, ?)", (PLATFORM, m.author))
            person = con.execute("SELECT id FROM person WHERE platform = ? AND platform_uid = ?", (PLATFORM, m.author)).fetchone()[0]
            cur = con.execute(
                "INSERT OR IGNORE INTO message(source, source_msg_id, chat_id, sender_id, ts, order_key, text, reply_to, media, nickname_at_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source, m.msg_id, chat, person, m.timestamp, order, m.content, m.reply_to, json.dumps(list(m.media)), m.nickname_at_time))
            if not cur.rowcount:
                continue
            if m.nickname_at_time:
                con.execute("INSERT INTO person_name VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(person_id, chat_id, name) "
                            "DO UPDATE SET last_seen = max(last_seen, excluded.last_seen)",
                            (person, chat, m.nickname_at_time, m.timestamp, m.timestamp, cur.lastrowid))
            order, added, persons = order + 1, added + 1, persons | {person}
            first, last = (m.timestamp if first is None else first), m.timestamp
    return {"in_export": len(messages), "already_there": sum(m.msg_id in have for m in messages), "added": added,
            "senders": len(persons), "first_added_ts": first, "last_added_ts": last,
            "export_last_ts": messages[-1].timestamp if messages else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--exports", type=Path, required=True, help="folder of <group number>.jsonl ChatLab files")
    ap.add_argument("--codes", required=True, help="comma-separated group codes to take; other files are not read")
    ap.add_argument("--frozen-codes", default="", help="codes never to import, where the research selection is not available")
    args = ap.parse_args()
    wanted = {c.strip() for c in args.codes.split(",") if c.strip()}
    frozen = {c.strip() for c in args.frozen_codes.split(",") if c.strip()}
    try:
        from bench import realdata
        from bench.schema import Visibility
        frozen |= {c for c, v in realdata.splits().items() if v is Visibility.FROZEN}
    except (OSError, ValueError, KeyError):
        if not frozen:
            raise SystemExit("no research selection here: give --frozen-codes")
    if wanted & frozen:
        raise SystemExit("FROZEN groups are not imported")
    store, out = Store(args.db), {}
    for path in sorted(args.exports.glob("*.jsonl")):
        code = code_of(path.stem)
        if code in wanted:
            out[code] = backfill(store, path, code)
    out["indexed"] = store.index_missing()
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
