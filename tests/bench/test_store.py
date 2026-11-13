import json

from bench import realdata
from bench.store import importer


def export(tmp_path, monkeypatch, lines, colors):
    """A made-up group export and colour file on disk; returns (group code, run folder)."""
    data = tmp_path / "data"
    (data / "reconciled").mkdir(parents=True)
    rows = [{"_type": "header"}]
    for i, (sender, text) in enumerate(lines):
        rows.append({"_type": "message", "platformMessageId": f"m{i}", "sender": sender, "timestamp": 100 + i,
                     "content": text, "type": 0, "groupNickname": f"昵称{sender}"})
    (data / "reconciled" / "g1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    code = realdata.pseudonym("g1")
    (data / "selection.json").write_text(json.dumps({"groups": {code: "DEV"}}))
    monkeypatch.setattr(realdata, "DATA_DIR", data)
    run = tmp_path / "run"
    run.mkdir()
    (run / "colors.test.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in colors))
    return code, run


def test_import_round_trips_messages_and_colours(tmp_path, monkeypatch):
    colors = [{"color_id": "b0c0", "msg_ids": ["m2", "m0"], "summary": "吃火锅", "labels": ["事件"]},
              {"color_id": "b0c1", "msg_ids": ["m1"], "summary": "附和", "labels": []}]
    code, run = export(tmp_path, monkeypatch, [("u1", "今天吃火锅"), ("u2", "好啊"), ("u1", "在学校后门")], colors)

    con = importer.connect(tmp_path / "m.db")
    mapper = importer.Mapper(con)
    stats = importer.import_group(con, mapper, code, run)
    assert stats["messages"] == 3 and stats["colors"] == 2 and stats["unresolved_links"] == 0
    assert importer.messages_from_db(con, code) == realdata.load_group(code)
    assert importer.colors_from_db(con, code, "colors.test.jsonl") == colors
    kinds = {r["kind"] for r in mapper.rows}
    assert kinds == {"chat", "person", "message", "color_run", "color"}
    person = [r for r in mapper.rows if r["kind"] == "person" and r["old"] == "u1"][0]
    assert person["extra"] == "P001"


def test_frozen_retrieval_from_the_store_shows_names_and_leaves_later_messages_to_message_search(tmp_path, monkeypatch):
    import hashlib

    import numpy as np

    from bench.frozen import FROZEN
    from bench.store import frozen
    from bothost.store import Store

    lines = [("u1", "周末去吃火锅吗"), ("u2", "火锅可以，学校后门那家"), ("u1", "昵称u2 记得订位"), ("u2", "羽毛球拍谁借走了"),
             ("u3", "在我这，明天还"), ("u1", "期末考试改到周三"), ("u3", "周三上午还是下午"), ("u1", "上午九点")]
    colors = [{"color_id": "b0c0", "msg_ids": ["m0", "m1", "m2"], "summary": "P001 和 P002 约周末吃火锅", "labels": []},
              {"color_id": "b0c1", "msg_ids": ["m3", "m4"], "summary": "P002 找羽毛球拍", "labels": []},
              {"color_id": "b0c2", "msg_ids": ["m5", "m6", "m7"], "summary": "期末考试改到周三上午九点", "labels": []}]
    code, run = export(tmp_path, monkeypatch, lines, colors)
    db = tmp_path / "m.db"
    con = importer.connect(db)
    importer.import_group(con, importer.Mapper(con), code, run)
    con.commit()
    config = {**FROZEN, "colors": "colors.test.jsonl"}

    def vector(key):
        return np.frombuffer(hashlib.sha256(key.encode()).digest() * 96, dtype=np.uint8)[:768].astype(np.float32)

    monkeypatch.setattr(frozen, "vectors_in_file", lambda path, keys: {k: vector(k) for k in keys})
    emb = frozen.StoreEmbedder(con, config, tmp_path / "cache.jsonl")
    frozen.load(con, code, emb, config)
    assert emb.copied == con.execute("SELECT count(*) FROM embedding").fetchone()[0] == 6   # 3 summaries, 3 raw blocks

    store = Store(db)
    store.add(code, "9", 500.0, "u9", "新人", "火锅那家后来关门了")   # recorded by the bot later: not part of the frozen corpus
    memory = frozen.FrozenMemory(db, config)

    def no_service(self, texts, task):
        raise RuntimeError("down")

    monkeypatch.setattr(frozen.StoreEmbedder, "_request", no_service)
    found, vectors = memory.search("昵称u2 火锅")
    assert not vectors and [(m.nickname_at_time, m.content) for m in found[code][0]] == [(f"昵称{s}", t) for s, t in lines[:3]]
    monkeypatch.setattr(frozen.StoreEmbedder, "_request", lambda self, texts, task: [[1.0] * 768 for _ in texts])
    found, vectors = memory.search("昵称u2 火锅")
    assert vectors and {m.content for part in found[code] for m in part} >= {t for _, t in lines[:3]}
    assert memory.search("火锅", exclude=(code,)) == ({}, True) and memory.search("火锅", as_of=100.5)[0] == {code: []}
    newer = {c: g.end_ts for c, g in memory.load().items()}
    assert len(store.search("火锅", 5)) > 1 and [h["lines"][-1]["name"] for h in store.search("火锅", 5, newer=newer)] == ["新人"]
