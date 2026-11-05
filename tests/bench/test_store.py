import json

from bench import realdata
from bench.store import importer


def test_import_round_trips_messages_and_colours(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "reconciled").mkdir(parents=True)
    rows = [{"_type": "header"}]
    for i, (sender, text) in enumerate([("u1", "今天吃火锅"), ("u2", "好啊"), ("u1", "在学校后门")]):
        rows.append({"_type": "message", "platformMessageId": f"m{i}", "sender": sender, "timestamp": 100 + i,
                     "content": text, "type": 0, "groupNickname": f"昵称{sender}"})
    (data / "reconciled" / "g1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    code = realdata.pseudonym("g1")
    (data / "selection.json").write_text(json.dumps({"groups": {code: "DEV"}}))
    monkeypatch.setattr(realdata, "DATA_DIR", data)
    run = tmp_path / "run"
    run.mkdir()
    colors = [{"color_id": "b0c0", "msg_ids": ["m2", "m0"], "summary": "吃火锅", "labels": ["事件"]},
              {"color_id": "b0c1", "msg_ids": ["m1"], "summary": "附和", "labels": []}]
    (run / "colors.test.jsonl").write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in colors))

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
