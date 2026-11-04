import json
import re

from bench import labeling
from bench.schema import Message


def msg(i, text, author="P001", ts=None):
    return Message(f"real-id-{i}", "g", author, float(i if ts is None else ts), text)


QUESTIONS = [{"id": "q2:1", "question": "问", "answer": "答", "gold": ["real-id-2"]}]
REPORT = {"qa": [
    {"arm": "S0", "rows": [
        {"id": "q2:1", "visible": True, "answer": "甲", "correct": True},
        {"id": "q2:1", "visible": False, "answer": "没有记录", "refused": True},
    ]},
    {"arm": "base", "rows": [{"id": "q2:1", "visible": True, "answer": "甲", "correct": False}]},
    {"arm": "other", "rows": [{"id": "q2:1", "visible": True, "answer": "乙", "correct": False}]},
]}


def test_question_card_marks_gold_and_hides_ids_and_sensitive():
    msgs = [msg(0, "早"), msg(1, "我的身份证丢了"), msg(2, "证据"), msg(3, "晚")]
    task = labeling.question_tasks(QUESTIONS, msgs)[0]
    assert [line["text"] for line in task["lines"] if line["gold"]] == ["证据"]
    dump = json.dumps(task, ensure_ascii=False)
    assert "身份证" not in dump and "real-id" not in dump


def test_same_answer_shares_a_card_and_arm_is_hidden():
    tasks, mapping = labeling.answer_tasks(REPORT, QUESTIONS, 10, 0)
    assert len(tasks) == 2 and sorted(t["model_answer"] for t in tasks) == ["乙", "甲"]
    assert "没有记录" not in json.dumps(tasks, ensure_ascii=False)
    dump = json.dumps(tasks)
    assert "S0" not in dump and "base" not in dump
    assert sorted(sorted(v["arms"]) for v in mapping.values()) == [["S0", "base"], ["other"]]


def test_term_examples_never_come_from_after_learning():
    msgs = [msg(1, "绝活哥早", ts=1), msg(2, "绝活哥晚", ts=100)]
    entry = {"term": "绝活哥", "meaning": "m", "learned_before": 50}
    assert [x["text"] for x in labeling.term_tasks([entry], msgs, 5, 0)[0]["lines"]] == ["绝活哥早"]


def test_assign_shares_overlap_and_covers_everything():
    tasks = [{"id": f"a:{i}", "type": "a"} for i in range(10)] + [{"id": "b:0", "type": "b"}]
    packs = labeling.assign(tasks, 3, 2, 0)
    ids = [{t["id"] for t in p} for p in packs]
    assert set().union(*ids) == {t["id"] for t in tasks}
    assert len(ids[0] & ids[1] & ids[2]) == 3
    assert max(map(len, packs)) - min(map(len, packs)) <= 1


def test_page_embeds_data_safely():
    page = labeling.render_page("A", [{"id": "x", "type": "term", "term": "</script><b>"}], [])
    block = re.search(r'<script id="data" type="application/json">(.*?)</script>', page, re.S).group(1)
    assert json.loads(block)["tasks"][0]["term"] == "</script><b>"


def test_corpus_uses_local_numbers():
    corpus, numbers = labeling.corpus_of([msg(1, "一"), msg(2, "密码是这个"), msg(3, "三")])
    assert [c["n"] for c in corpus] == [0, 1] and numbers == {"0": "real-id-1", "1": "real-id-3"}
    assert "real-id" not in json.dumps(corpus)


def test_kappa():
    assert labeling.cohen_kappa(["a", "b"], ["a", "b"]) == 1.0
    assert labeling.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    assert labeling.cohen_kappa(["a"], ["a"]) == 1.0
    assert labeling.cohen_kappa([], []) is None


def test_merge_uses_human_verdicts_and_drops_rejected_questions():
    manifest = {"answers": {"answer:0": {"question": "q2:1", "arms": ["S0", "base"]}}, "numbers": {"7": "real-id-7"}}
    results = [
        {"name": "x", "labels": {"answer:0": "incorrect", "term:词": "right", "question:q2:9": "wrong"},
         "written": [{"question": "新", "answer": "答", "evidence": [7, 99]}]},
        {"name": "y", "labels": {"answer:0": "incorrect", "term:词": "notterm"}},
        {"name": "z", "labels": {"answer:0": "skip"}},
    ]
    out = labeling.merge(results, manifest, REPORT)
    assert out["arms"]["S0"] == {"questions": 1, "human_verdicts": 1, "accuracy": 0.0, "accuracy_without_awkward": 0.0}
    assert out["arms"]["other"]["human_verdicts"] == 0
    assert out["judge_vs_human"] == {"n": 2, "agreement": 0.5}
    assert out["conflicts"] == ["term:词:kind"]
    assert out["terms"]["labels"] == {}
    assert out["questions"]["rejected"] == ["q2:9"]
    assert out["written_questions"][0]["gold"] == ["real-id-7"]


def test_skips_are_left_out_of_agreement():
    results = [{"labels": {"term:a": "right", "term:b": SKIP}} for SKIP in ["skip"]] + [{"labels": {"term:a": "right", "term:b": "right"}}]
    assert labeling.agreement(results)["term"]["pairs"] == 1


def test_awkward_questions_are_kept_but_reported_apart():
    manifest = {"answers": {}, "numbers": {}}
    results = [{"labels": {"question:q2:1": "awkward"}}]
    out = labeling.merge(results, manifest, REPORT)
    assert out["questions"]["awkward"] == ["q2:1"] and out["questions"]["rejected"] == []
    assert out["arms"]["S0"]["questions"] == 1 and out["arms"]["S0"]["accuracy_without_awkward"] is None


def test_old_term_labels_map_onto_current_codes():
    results = [{"labels": {"term:a": "right", "term:b": "general", "term:c": "badmeaning", "term:d": "person"},
                "notes": {"term:c": "正确意思", "term:d": " "}}]
    out = labeling.merge(results, {"answers": {}, "numbers": {}}, {"qa": []})
    assert out["terms"]["labels"] == {"specific_ok": 1, "general_ok": 1, "specific_bad": 1, "person": 1}
    assert out["terms"]["is_term_rate"] == 0.75 and out["terms"]["group_specific_rate"] == 0.5
    assert out["terms"]["meaning_correct_rate"] == round(2 / 3, 4)
    assert out["notes"] == {"term:c": "正确意思"}


def test_knowledge_questions_and_bad_answer_cards_are_flagged():
    manifest = {"answers": {"answer:0": {"question": "q2:1", "arms": ["S0"]}}, "numbers": {}}
    results = [{"labels": {"question:q2:5": "knowledge", "answer:0": "badquestion"}}]
    out = labeling.merge(results, manifest, REPORT)
    assert out["questions"]["rejected"] == ["q2:5"]
    assert out["questions_flagged_from_answers"] == ["q2:1"]
    assert out["judge_vs_human"]["n"] == 0


def test_term_votes_ignore_scope_and_count_notes_as_corrections():
    results = [
        {"labels": {"term:pr": "specific_ok"}, "notes": {"term:pr": "普瑞巴林"}},
        {"labels": {"term:pr": "general_bad"}, "notes": {}},
        {"labels": {"term:pr": "general_ok"}, "notes": {}},
    ]
    votes, conflicts = labeling.term_votes(results)
    assert votes["term:pr"] == {"kind": "term", "meaning": False, "scope": "general"}
    assert conflicts == []


def test_term_person_majority_skips_meaning_conflict():
    results = [{"labels": {"term:x": "person"}}, {"labels": {"term:x": "person"}}, {"labels": {"term:x": "general_ok"}}]
    votes, conflicts = labeling.term_votes(results)
    assert votes["term:x"]["kind"] == "person" and conflicts == []


def test_rulings_override_votes():
    results = [{"labels": {"term:x": "specific_ok", "answer:0": "correct"}}, {"labels": {"term:x": "general_ok", "answer:0": "incorrect"}}]
    manifest = {"answers": {"answer:0": {"question": "q2:1", "arms": ["S0"]}}, "numbers": {}}
    out = labeling.merge(results, manifest, REPORT, {"term:x": {"kind": "person"}, "answer:0": "incorrect"})
    assert out["term_votes"]["x"] == {"kind": "person"}
    assert out["conflicts"] == [] and out["arms"]["S0"]["accuracy"] == 0.0
