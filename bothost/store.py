"""The one message store (schema: bench/store/schema.sql): imported history and live messages together.

Raw messages are append-only. The keyword index is updated with every message: FTS5 finds the candidates,
the score is the BM25Okapi formula of bench.retrievers.bm25 computed from statistics kept next to the index.
"""
from __future__ import annotations

import math
import sqlite3
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "bench" / "store" / "schema.sql"
TZ = timezone(timedelta(hours=8))
K1, B, EPSILON = 1.5, 0.75, 0.25   # as in bench.retrievers.bm25.BM25


def stamp(ts: float, fmt: str = "%Y-%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(ts, TZ).strftime(fmt)


def line(ts: float, name: str, text: str, fmt: str = "%m-%d %H:%M") -> str:
    return f"[{stamp(ts, fmt)}] {name}: {text}"


class Store:
    def __init__(self, path: Path, platform: str = "qq") -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = Path(path)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA.read_text(encoding="utf-8"))
        self.platform = platform
        self._tokenize = None
        self._floor: tuple[float, float] | None = None   # (corpus size it was computed for, value)
        self.index_missing()

    # ---- writing ----
    def tokens(self, text: str) -> list[str]:
        if self._tokenize is None:   # jieba loads its dictionary on first use; not needed just to record messages
            from bench.tokenize import make_jieba
            self._tokenize = make_jieba()
        return [t for t in self._tokenize(text) if not t.isspace()]

    def _index(self, rows) -> int:
        n = total = 0
        for mid, text in rows:
            toks = self.tokens(text)
            self.db.execute("INSERT INTO message_fts(rowid, body, dl) VALUES (?, ?, ?)", (mid, " ".join(toks), len(toks)))
            self.db.executemany("INSERT INTO message_df VALUES (?, 1) ON CONFLICT(term) DO UPDATE SET df = df + 1",
                                [(t,) for t in set(toks)])
            n, total = n + 1, total + len(toks)
        if n:
            self.db.executemany("INSERT INTO message_fts_meta VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = v + excluded.v",
                                [("n", n), ("total", total)])
        return n

    def index_missing(self) -> int:
        """Index messages that are not in the keyword index yet (first run, or rows added by the importer)."""
        with self.db:
            return self._index(self.db.execute(
                "SELECT id, text FROM message WHERE id > (SELECT coalesce(max(rowid), 0) FROM message_fts) ORDER BY id").fetchall())

    def _person(self, uid: str) -> int | None:
        """The person behind a live account id: one linked to imported history if there is such a link."""
        row = self.db.execute(
            "SELECT person_id FROM person_account WHERE platform = ? AND account = ? "
            "UNION ALL SELECT id FROM person WHERE platform = ? AND platform_uid = ?",
            (self.platform, uid, self.platform, uid)).fetchone()
        return row[0] if row else None

    def add(self, code: str, msg_id: str, ts: float, uid: str, name: str, text: str, reply_to: str = "") -> None:
        """Record one live message. code is the group's alias, never the real group id."""
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO chat(platform, code) VALUES (?, ?)", (self.platform, code))
            chat = self.db.execute("SELECT id FROM chat WHERE code = ?", (code,)).fetchone()[0]
            person = self._person(uid)
            if person is None:
                person = self.db.execute("INSERT INTO person(platform, platform_uid) VALUES (?, ?)", (self.platform, uid)).lastrowid
            order = self.db.execute("SELECT coalesce(max(order_key), -1) + 1 FROM message WHERE chat_id = ?", (chat,)).fetchone()[0]
            cur = self.db.execute(
                "INSERT OR IGNORE INTO message(source, source_msg_id, chat_id, sender_id, ts, order_key, text, reply_to, nickname_at_time) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{self.platform}:{code}", _live_id(msg_id), chat, person, ts, order, text, _live_id(reply_to) if reply_to else None, name))
            if not cur.rowcount:
                return
            self.db.execute(
                "INSERT INTO person_name VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(person_id, chat_id, name) DO UPDATE SET last_seen = excluded.last_seen",
                (person, chat, name, ts, ts, cur.lastrowid))
            self._index([(cur.lastrowid, text)])

    def retext(self, code: str, msg_id: str, text: str) -> bool:
        """Replace the text of a live message (e.g. a picture placeholder by what the model saw in it), keeping the
        keyword index and its BM25 statistics in step. False when there is no such message."""
        row = self.db.execute("SELECT id, text FROM message WHERE source = ? AND source_msg_id = ?",
                              (f"{self.platform}:{code}", _live_id(msg_id))).fetchone()
        if row is None or row["text"] == text:
            return row is not None
        old, new = self.tokens(row["text"]), self.tokens(text)
        with self.db:
            self.db.execute("UPDATE message SET text = ? WHERE id = ?", (text, row["id"]))
            self.db.execute("DELETE FROM message_fts WHERE rowid = ?", (row["id"],))
            self.db.execute("INSERT INTO message_fts(rowid, body, dl) VALUES (?, ?, ?)", (row["id"], " ".join(new), len(new)))
            self.db.executemany("UPDATE message_df SET df = df - 1 WHERE term = ?", [(t,) for t in set(old)])
            self.db.executemany("INSERT INTO message_df VALUES (?, 1) ON CONFLICT(term) DO UPDATE SET df = df + 1", [(t,) for t in set(new)])
            self.db.execute("DELETE FROM message_df WHERE df <= 0")
            self.db.execute("UPDATE message_fts_meta SET v = v + ? WHERE k = 'total'", (len(new) - len(old),))
        self._floor = None
        return True

    # ---- reading ----
    def shown_name(self, code: str, uid: str) -> str | None:
        """The name an account was last shown under in this chat, else in any chat."""
        person = self._person(uid)
        if person is None:
            return None
        row = self.db.execute(
            "SELECT pn.name FROM person_name pn JOIN chat c ON c.id = pn.chat_id WHERE pn.person_id = ? "
            "ORDER BY (c.code = ?) DESC, pn.last_seen DESC LIMIT 1", (person, code)).fetchone()
        return row[0] if row else None

    def is_from(self, code: str, msg_id: str, uid: str) -> bool:
        return bool(msg_id) and self.db.execute(
            "SELECT 1 FROM message WHERE source = ? AND source_msg_id = ? AND sender_id = ?",
            (f"{self.platform}:{code}", _live_id(msg_id), self._person(uid))).fetchone() is not None

    def recent(self, code: str, n: int, before_ts: float = math.inf, skip: str = "") -> list[sqlite3.Row]:
        """The last n lines of a chat. skip: leave out lines whose id starts with this (one session of a private chat)."""
        rows = self.db.execute(
            "SELECT m.ts, m.nickname_at_time AS name, m.text FROM message m JOIN chat c ON c.id = m.chat_id "
            "WHERE c.code = ? AND m.ts < ? AND (? = '' OR substr(m.source_msg_id, 1, ?) != ?) ORDER BY m.order_key DESC LIMIT ?",
            (code, before_ts, skip, len(_live_id(skip)), _live_id(skip), n)).fetchall()
        return rows[::-1]

    def uncoloured(self, code: str) -> int:
        """How many of a group's messages come after the last one any colour covers."""
        return self.db.execute(
            "SELECT count(*) FROM message m JOIN chat c ON c.id = m.chat_id WHERE c.code = ? AND m.order_key > coalesce("
            "(SELECT max(x.order_key) FROM color_link l JOIN message x ON x.id = l.message_id WHERE x.chat_id = c.id), -1)",
            (code,)).fetchone()[0]

    def catalog(self, exclude: tuple[str, ...] = ()) -> list[sqlite3.Row]:
        """Groups with message counts and time ranges, most recently active first."""
        return [r for r in self.db.execute(
            "SELECT c.code, count(*) AS messages, min(m.ts) AS first, max(m.ts) AS last, count(DISTINCT m.sender_id) AS people "
            "FROM message m JOIN chat c ON c.id = m.chat_id GROUP BY c.id ORDER BY last DESC") if r["code"] not in exclude]

    def _idf(self, term: str, n: float) -> float | None:
        row = self.db.execute("SELECT df FROM message_df WHERE term = ?", (term,)).fetchone()
        if row is None:
            return None
        idf = math.log(n - row[0] + 0.5) - math.log(row[0] + 0.5)
        if idf >= 0:
            return idf
        if self._floor is None or self._floor[0] != n:   # only for terms in more than half of all messages
            all_idf = [math.log(n - df + 0.5) - math.log(df + 0.5) for (df,) in self.db.execute("SELECT df FROM message_df")]
            self._floor = (n, EPSILON * sum(all_idf) / len(all_idf))
        return self._floor[1]

    def search(self, query: str, limit: int = 6, groups: tuple[str, ...] = (), as_of: float = math.inf,
               exclude: tuple[str, ...] = (), around: int = 2, newer: dict[str, float] | None = None) -> list[dict]:
        """Best-matching messages over all groups (or the given ones), each with its neighbours in the same group.

        newer: group -> time; in those groups only later messages count (the earlier part is searched through its colours).
        """
        terms = self.tokens(query)
        meta = dict(self.db.execute("SELECT k, v FROM message_fts_meta").fetchall())
        n, total = meta.get("n", 0), meta.get("total", 0)
        idf = {t: v for t in set(terms) if (v := self._idf(t, n)) is not None}
        if not idf or not total:
            return []
        sql = ("SELECT f.rowid AS id, f.body, f.dl, c.code, m.ts FROM message_fts f JOIN message m ON m.id = f.rowid JOIN chat c ON c.id = m.chat_id "
               "WHERE message_fts MATCH ? AND m.ts < ?")
        args: list = [" OR ".join('"' + t.replace('"', '""') + '"' for t in idf), as_of]
        for codes, op in ((groups, "IN"), (exclude, "NOT IN")):
            if codes:
                sql += f" AND c.code {op} ({','.join('?' * len(codes))})"
                args += codes
        avgdl, scored = total / n, []
        for r in self.db.execute(sql, args):
            if newer and r["ts"] <= newer.get(r["code"], -math.inf):
                continue
            tf, norm, s = Counter(r["body"].split(" ")), K1 * (1 - B + B * r["dl"] / avgdl), 0.0
            for t in terms:   # repeated query terms count again, as in BM25Okapi
                if t in idf and tf[t]:
                    s += idf[t] * tf[t] * (K1 + 1) / (tf[t] + norm)
            if s > 0:
                scored.append((-s, r["id"]))
        hits = []
        for neg, mid in sorted(scored)[:limit]:
            rows = self.db.execute(
                "SELECT m.id, c.code, m.ts, m.nickname_at_time AS name, m.text FROM message m JOIN chat c ON c.id = m.chat_id, "
                "(SELECT chat_id, order_key FROM message WHERE id = ?) h "
                "WHERE m.chat_id = h.chat_id AND m.order_key BETWEEN h.order_key - ? AND h.order_key + ? ORDER BY m.order_key",
                (mid, around, around)).fetchall()
            hits.append({"id": mid, "chat": rows[0]["code"], "score": round(-neg, 3),
                         "lines": [{"hit": r["id"] == mid, "ts": r["ts"], "name": r["name"] or "?", "text": r["text"]} for r in rows]})
        return hits


def _live_id(msg_id: str) -> str:
    """Ids from the protocol side get a prefix so they cannot collide with ids from imported exports."""
    return f"ob:{msg_id}" if msg_id else f"local:{uuid.uuid4().hex}"
