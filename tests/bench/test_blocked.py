import json

from bench import blocked


def test_marks_any_empty_answer_and_rescoring_drops_marked_questions(tmp_path):
    raw = tmp_path / "raw" / "abcd"
    raw.mkdir(parents=True)
    records = [
        {"question_id": "q1", "visible": True, "answer": {"output": "Final: x"}},
        {"question_id": "q2", "visible": False, "answer": {"output": ""}},
        {"question_id": "q3", "visible": True, "answer": {"output": None}},
    ]
    (raw / "A.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    data = blocked.write(tmp_path)
    assert data["count"] == 2 and blocked.load(tmp_path) == {"q2", "q3"}

    rows = [
        {"id": "q1", "visible": True, "correct": True, "overlap": "low"},
        {"id": "q2", "visible": True, "correct": False},
        {"id": "q3", "visible": True, "correct": False},
        {"id": "q1", "visible": False, "refused": True},
        {"id": "q2", "visible": False, "refused": False},
    ]
    m = blocked.rescore(rows, blocked.load(tmp_path))
    assert m["n"] == 1 and m["accuracy"] == 1.0 and m["refusal_when_absent"] == 1.0
    d = blocked.paired(rows, [dict(r, correct=False) if r["visible"] else r for r in rows], {"q2", "q3"})
    assert d["n"] == 1 and d["delta"] == -1.0
