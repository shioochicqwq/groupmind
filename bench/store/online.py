"""Colouring after going live (D-047): each job is a colour run of its own, continuing the frozen batches.

A group's colourable history is the imported export its frozen colours were made from (when it has them), then its
online runs in order. An online run records in `note` the batches it coloured, as lists of message ids; its first batch
starts with the last `overlap` messages of the batch before, the way consecutive frozen batches overlap, so the frozen
overlap handling (D-032) works across the seam. Colour ids are numbered on from the batches before: `b<batch>c<n>`.

The sanitizer (people as aliases, links and numbers masked) grows the same way: the frozen one is built from the export
and each run extends it with its own new messages. The text a colour was made from, and the vector keys that come from
it, are therefore the same whenever the history is rebuilt, and the frozen part is exactly what it was.

A group without frozen colours gets its live messages coloured, not its imported history.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass, field, replace

from bench import coloring
from bench.frozen import FROZEN
from bench.run_s0 import sanitized
from bench.sanitize import Sanitizer, is_sensitive
from bench.schema import Message
from bench.store.importer import colors_from_db
from bench.tasks.real_tasks import clean_messages

ONLINE = "online:"          # source_file prefix of the runs made here
SETTLE_S = 1800.0           # newer messages wait: a sticker or picture may still get its machine-written text


def extend(san: Sanitizer, messages: list[Message]) -> Sanitizer:
    """A copy of san that also knows the people in messages, numbered on, with later nicknames winning as in Sanitizer."""
    out = Sanitizer(())
    out.alias = dict(san.alias)
    nicks = dict(san.nick_alias)
    for m in messages:
        out.alias.setdefault(m.author, f"P{len(out.alias) + 1:03d}")
        if len(m.nickname_at_time) >= 2:
            nicks[m.nickname_at_time] = out.alias[m.author]
    out.nick_alias = sorted(nicks.items(), key=lambda kv: -len(kv[0]))
    return out


def _rows(con: sqlite3.Connection, code: str) -> list[tuple[int, bool, Message]]:
    """(order_key, live, message) for every message of a chat, in order."""
    rows = con.execute(
        "SELECT m.order_key, m.source_msg_id, p.platform_uid, m.ts, m.text, m.reply_to, m.media, m.nickname_at_time "
        "FROM message m JOIN chat c ON c.id = m.chat_id JOIN person p ON p.id = m.sender_id WHERE c.code = ? ORDER BY m.order_key",
        (code,)).fetchall()
    return [(r[0], r[1].startswith(("ob:", "local:")),
             Message(msg_id=r[1], channel=code, author=r[2], timestamp=r[3], content=r[4], reply_to=r[5],
                     media=tuple(json.loads(r[6] or "[]")), nickname_at_time=r[7])) for r in rows]


@dataclass
class History:
    code: str
    frozen: bool                       # the group has the frozen colour file
    san: Sanitizer                     # after the last run
    messages: list[Message]            # sanitized, the frozen corpus first, then each run's new messages
    clean: list[Message]               # the same messages as written (indexable text only)
    colors: list[dict]                 # frozen colours, then each run's, numbered on
    batches: list[list[Message]]       # clean messages per batch, in the same numbering
    frozen_messages: list[Message]     # the sanitized export: the learned words come from it
    frozen_colors: list[dict]
    last_order: int                    # order_key of the last message the runs have dealt with; -1: none
    size: int = 150
    overlap: int = 20
    runs: list[int] = field(default_factory=list)


@dataclass
class Run:
    """A run being made: its batches, the new messages it brings, and the colours once they are back."""
    batches: list[list[Message]]
    new: list[Message]                 # raw, in order
    san: Sanitizer                     # the history's sanitizer extended with `new`
    last_order: int
    colors: list[dict] = field(default_factory=list)
    failed: int = 0

    def prompts(self) -> list[str]:
        return [coloring.render(b, self.san) for b in self.batches]

    def note(self) -> dict:
        return {"batches": [[m.msg_id for m in b] for b in self.batches], "last_order": self.last_order, "failed": self.failed}


def history(con: sqlite3.Connection, code: str, config: dict = FROZEN, pending: Run | None = None,
            online: bool = True) -> History:
    """The colourable history of a chat as the colours saw it. pending: a run not stored yet, taken as the last one.
    online=False: the frozen part only."""
    rows = _rows(con, code)
    run = con.execute("SELECT r.batch_size, r.overlap FROM color_run r JOIN chat c ON c.id = r.chat_id "
                      "WHERE c.code = ? AND r.source_file = ?", (code, config["colors"])).fetchone()
    if run:
        imported = {old for (old,) in con.execute("SELECT old_id FROM id_map WHERE kind = 'message' AND chat_code = ?", (code,))}
        raw = [m for _, _, m in rows if m.msg_id in imported]
        san, clean = Sanitizer(raw), clean_messages(raw)
        messages, colors = sanitized(clean, san), colors_from_db(con, code, config["colors"])
        h = History(code, True, san, messages, clean, colors, coloring.batches(clean, run[0], run[1]), messages, colors,
                    max((o for o, _, m in rows if m.msg_id in imported), default=-1), run[0], run[1])
    else:
        h = History(code, False, Sanitizer(()), [], [], [], [], [], [], -1)
    if not online:
        return h
    by_id = {m.msg_id: m for _, _, m in rows}
    stored = con.execute("SELECT r.id, r.note FROM color_run r JOIN chat c ON c.id = r.chat_id WHERE c.code = ? AND r.source_file LIKE ? "
                         "ORDER BY r.id", (code, ONLINE + "%")).fetchall()
    for run_id, note in stored:
        note = json.loads(note)
        new = [m for o, live, m in rows if h.last_order < o <= note["last_order"] and (h.frozen or live)]
        made = Run([], new, extend(h.san, new), note["last_order"], _stored_colors(con, run_id), note.get("failed", 0))
        made.batches = [[m for m in clean_messages([by_id[i] for i in b if i in by_id])] for b in note["batches"]]
        _append(h, made)
        h.runs.append(run_id)
    if pending is not None:
        _append(h, pending)
    return h


def _stored_colors(con: sqlite3.Connection, run_id: int) -> list[dict]:
    out = []
    for cid, name, summary, labels in con.execute("SELECT id, name, summary, labels FROM color WHERE run_id = ? ORDER BY seq", (run_id,)):
        ids = [r[0] for r in con.execute(
            "SELECT m.source_msg_id FROM color_link l JOIN message m ON m.id = l.message_id WHERE l.color_id = ? ORDER BY l.pos", (cid,))]
        out.append({"color_id": name, "msg_ids": ids, "summary": summary, "labels": json.loads(labels)})
    return out


def _append(h: History, run: Run) -> None:
    """Add a run to the history: its new messages under its sanitizer, its colours and batches numbered on."""
    clean = clean_messages(run.new)
    h.san = run.san
    h.clean += clean
    h.messages += sanitized(clean, run.san)
    first = len(h.batches)
    for c in run.colors:
        b, n = c["color_id"][1:].split("c")
        h.colors.append({**c, "color_id": f"b{first + int(b)}c{n}"})
    h.batches += run.batches
    h.last_order = max(h.last_order, run.last_order)


def plan(con: sqlite3.Connection, h: History, final: bool, now: float | None = None) -> Run | None:
    """The next run: the messages after the last one dealt with, in batches of `size` that overlap the batch before by
    `overlap`. A batch is only made when it is full, unless final (a new session: nothing earlier is in front of the
    model any more). Messages younger than SETTLE_S are left for later. None when there is nothing to colour."""
    now = time.time() if now is None else now
    due = [(o, m) for o, live, m in _rows(con, h.code) if o > h.last_order and (h.frozen or live)]
    young = next((k for k, (_, m) in enumerate(due) if m.timestamp >= now - SETTLE_S), len(due))
    due = due[:young]   # a run covers an unbroken stretch of the order, so it can be rebuilt from its bounds
    if not due:
        return None
    clean = clean_messages([m for _, m in due])
    usable = [i for i, m in enumerate(clean) if m.content and not is_sensitive(m.content)]
    context = h.batches[-1][-h.overlap:] if h.batches and h.overlap else []
    batches, at, last = [], 0, None
    while at < len(usable):
        take = h.size - len(context)
        part = usable[at:at + take]
        if len(part) < take and not final:
            break
        batch = context + [clean[i] for i in part]
        batches.append(batch)
        at += len(part)
        last = part[-1]
        context = batch[-h.overlap:] if h.overlap else []
    if not batches:
        return None
    end = len(due) - 1 if final and at == len(usable) else last
    new = [m for _, m in due[:end + 1]]
    return Run(batches, new, extend(h.san, new), due[end][0])


def take(run: Run, outputs: list[str | None]) -> None:
    """The model's answers, one per batch, as colours; a batch with no usable answer counts as failed."""
    run.colors, run.failed = [], 0
    for i, (batch, text) in enumerate(zip(run.batches, outputs)):
        got = coloring.parse_colors(text or "", batch, i)
        run.failed += not got
        run.colors += got


def store(con: sqlite3.Connection, code: str, run: Run, model: str, batch_size: int, overlap: int, vectors: dict | None = None,
          embed_model: str = "", note: dict | None = None) -> int:
    """Write the run, its colours and links, and the document vectors made for it, in one transaction. Returns the run id."""
    body = {**run.note(), **(note or {})}
    digest = hashlib.sha256(json.dumps([body, run.colors], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    with con:
        chat_id = con.execute("SELECT id FROM chat WHERE code = ?", (code,)).fetchone()[0]
        cur = con.execute("INSERT INTO color_run(chat_id, model, source_file, source_sha256, batch_size, overlap, note) VALUES (?, ?, ?, ?, ?, ?, ?)",
                          (chat_id, model, ONLINE + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), digest, batch_size, overlap,
                           json.dumps(body, ensure_ascii=False)))
        run_id = cur.lastrowid
        row_of = dict(con.execute("SELECT source_msg_id, id FROM message WHERE chat_id = ?", (chat_id,)).fetchall())
        for seq, c in enumerate(run.colors):
            cid = con.execute("INSERT INTO color(run_id, seq, name, summary, labels) VALUES (?, ?, ?, ?, ?)",
                              (run_id, seq, c["color_id"], c["summary"], json.dumps(c["labels"], ensure_ascii=False))).lastrowid
            con.executemany("INSERT OR IGNORE INTO color_link VALUES (?, ?, ?)", [(cid, row_of[i], pos) for pos, i in enumerate(c["msg_ids"])])
        if vectors:
            con.executemany("INSERT OR IGNORE INTO embedding VALUES (?, ?, ?)",
                            [(k, embed_model, v.astype("<f4").tobytes()) for k, v in vectors.items()])
    return run_id


def with_run(h: History, run: Run) -> History:
    """A copy of h with run appended (for building the index before the run is stored)."""
    out = replace(h, messages=list(h.messages), clean=list(h.clean), colors=list(h.colors), batches=list(h.batches), runs=list(h.runs))
    _append(out, run)
    return out
