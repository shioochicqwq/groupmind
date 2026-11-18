"""Colouring after going live (bench/store/online.py, bothost/colouring.py) on a made-up group."""
import hashlib
import json
import re

import numpy as np
import pytest

from bench.frozen import FROZEN
from bench.store import frozen, importer, online
from bothost.colouring import Colouring
from bothost.store import Store
from tests.bench.test_store import export

LINES = [("u1", "周末去吃火锅吗"), ("u2", "火锅可以，学校后门那家"), ("u1", "昵称u2 记得订位"), ("u2", "羽毛球拍谁借走了"),
         ("u3", "在我这，明天还"), ("u1", "期末考试改到周三"), ("u3", "周三上午还是下午"), ("u1", "上午九点")]
COLORS = [{"color_id": "b0c0", "msg_ids": ["m0", "m1", "m2"], "summary": "P001 和 P002 约周末吃火锅", "labels": []},
          {"color_id": "b0c1", "msg_ids": ["m3", "m4"], "summary": "P002 找羽毛球拍", "labels": []},
          {"color_id": "b0c2", "msg_ids": ["m5", "m6", "m7"], "summary": "期末考试改到周三上午九点", "labels": []}]


def vector(text):
    return [float(b) for b in hashlib.sha256(text.encode()).digest() * 24][:768]


@pytest.fixture
def group(tmp_path, monkeypatch):
    code, run = export(tmp_path, monkeypatch, LINES, COLORS)
    db = tmp_path / "m.db"
    con = importer.connect(db)
    importer.import_group(con, importer.Mapper(con), code, run)
    con.execute("UPDATE color_run SET source_file = ?", (FROZEN["colors"],))   # the frozen colour file, as on the bot
    con.execute("UPDATE id_map SET scope = ? WHERE kind = 'color'", (FROZEN["colors"],))
    con.commit()
    monkeypatch.setattr(frozen, "vectors_in_file", lambda path, keys: {k: np.ones(768, dtype=np.float32) for k in keys})
    frozen.load(con, code, frozen.StoreEmbedder(con, FROZEN, tmp_path / "cache.jsonl"))   # the frozen vectors, as imported
    con.commit()
    asked = []
    monkeypatch.setattr(frozen.StoreEmbedder, "_request", lambda self, texts, task: asked.extend(texts) or [vector(t) for t in texts])
    return code, db, con, asked


def colourer(db, tmp_path, monkeypatch, answers=None):
    c = Colouring(db, "colour-model", "http://gateway/v1", "k", tmp_path / "usage.jsonl")

    def ask(prompt):   # one colour per five lines, named after the batch's first line
        if answers is not None:
            return answers.pop(0), {"prompt_tokens": 10, "completion_tokens": 2}
        n = len(prompt.splitlines())
        first = prompt.splitlines()[0].split(": ", 1)[1]
        return json.dumps([{"type": "闲聊", "name": f"从{first}起", "summary": f"第{i}段", "ids": list(range(i, min(i + 5, n + 1)))}
                           for i in range(1, n + 1, 5)], ensure_ascii=False), {"prompt_tokens": 100, "completion_tokens": 20}

    monkeypatch.setattr(c, "_ask", ask)
    return c


def live(db, code, n, start=0, ts=1000.0):
    s = Store(db)
    for i in range(start, start + n):
        s.add(code, f"x{i}", ts + i, f"v{i % 4}", f"新人{i % 4}", f"第{i}句 话题{i // 30}")


def test_a_compaction_colours_full_batches_on_from_the_frozen_ones(group, tmp_path, monkeypatch):
    code, db, con, asked = group
    live(db, code, 200)
    got = colourer(db, tmp_path, monkeypatch).run(code, final=False, why="compaction")
    # the frozen batch has 8 messages: the first new batch carries them as its overlap and takes 142 new ones;
    # the 58 left do not fill another batch, so they wait
    assert got["batches"] == 1 and got["messages"] == 142 and got["failed_batches"] == 0 and got["vectors"] == len(asked) > 0
    run = con.execute("SELECT source_file, note FROM color_run ORDER BY id DESC").fetchone()
    note = json.loads(run[1])
    assert run[0].startswith("online:") and note["trigger"] == "compaction" and note["batches"][0][:8] == [f"m{i}" for i in range(8)]

    h = online.history(con, code)
    assert [c["color_id"] for c in h.colors][:3] == ["b0c0", "b0c1", "b0c2"] and h.colors[3]["color_id"] == "b1c0"
    assert len(h.batches) == 2 and h.san.alias["u1"] == "P001" and h.san.alias["v0"] == "P004"
    # rebuilt from the store, the history gives the same texts, so every vector is found without asking again
    asked.clear()
    memory = frozen.FrozenMemory(db)
    g = memory.load()[code]
    assert not asked and g.end_ts > 1000
    found, vectors = memory.search("话题3")
    assert vectors and any("话题3" in m.content for part in found[code] for m in part)
    assert Store(db).uncoloured(code) == 58


def test_a_new_session_colours_the_rest_and_recall_picks_it_up(group, tmp_path, monkeypatch):
    code, db, con, asked = group
    live(db, code, 200)
    c = colourer(db, tmp_path, monkeypatch)
    c.run(code, final=False)
    memory = frozen.FrozenMemory(db)
    before = memory.load()[code].end_ts
    got = c.run(code, final=True, why="cold_start")
    assert got["batches"] == 1 and got["messages"] == 58
    h = online.history(con, code)
    assert len(h.batches) == 3 and h.batches[2][:20] == h.batches[1][-20:]   # overlaps the batch before by 20
    assert Store(db).uncoloured(code) == 0 and c.run(code, final=True) == {"batches": 0}
    memory.search("话题6")   # a search rebuilds a chat that has a new run
    assert memory.load()[code].end_ts > before


def test_young_messages_wait_and_a_chat_without_frozen_colours_gets_its_live_messages_only(group, tmp_path, monkeypatch):
    code, db, con, asked = group
    import time
    live(db, code, 30, ts=time.time() - 60)   # just said: a sticker or picture may still change their text
    assert colourer(db, tmp_path, monkeypatch).run(code, final=True) == {"batches": 0}
    live(db, "dm", 12)
    got = colourer(db, tmp_path, monkeypatch).run("dm", final=True)
    assert got["messages"] == 12 and online.history(con, "dm").batches[0][0].content == "第0句 话题0"
    assert "dm" in frozen.FrozenMemory(db).load()


def test_a_failed_job_stores_nothing(group, tmp_path, monkeypatch):
    code, db, con, asked = group
    live(db, code, 200)
    c = colourer(db, tmp_path, monkeypatch)

    def down(prompt):
        raise TimeoutError

    monkeypatch.setattr(c, "_ask", down)
    with pytest.raises(TimeoutError):
        c.run(code, final=True)
    monkeypatch.setattr(frozen.StoreEmbedder, "_request", lambda self, texts, task: (_ for _ in ()).throw(RuntimeError("down")))
    c = colourer(db, tmp_path, monkeypatch)
    with pytest.raises(RuntimeError):
        c.run(code, final=True)
    assert con.execute("SELECT count(*) FROM color_run WHERE source_file LIKE 'online:%'").fetchone()[0] == 0


def test_an_answer_that_is_not_a_colour_list_is_asked_again_then_counted_as_failed(group, tmp_path, monkeypatch):
    code, db, con, asked = group
    live(db, code, 20)
    got = colourer(db, tmp_path, monkeypatch, answers=["抱歉", "还是不行"]).run(code, final=True)
    assert got["batches"] == 1 and got["failed_batches"] == 1 and got["colors"] == 0 and got["prompt"] == 20
    assert re.fullmatch(r"online:\S+", con.execute("SELECT source_file FROM color_run ORDER BY id DESC").fetchone()[0])
