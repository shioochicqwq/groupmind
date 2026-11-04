import json

import pytest

from bench import ledger


def test_row_requires_every_condition():
    with pytest.raises(ValueError):
        ledger.row("e", "a", {"index": "x"}, {}, dataset="d", split="s")
    r = ledger.row("e", "a", ledger.cond(index="x"), {"accuracy": 0.5}, dataset="d", split="s")
    assert r["conditions"]["budget_chars"] == "-" and r["code"]["commit"]


def test_append_replaces_same_arm_and_keeps_others(tmp_path):
    path = tmp_path / "l.jsonl"
    mk = lambda arm, acc: ledger.row("e", arm, ledger.cond(), {"accuracy": acc}, dataset="d", split="s")  # noqa: E731
    ledger.append(path, [mk("a", 0.1), mk("b", 0.2)])
    ledger.append(path, [mk("a", 0.3)])
    rows = [json.loads(x) for x in path.read_text().splitlines()]
    assert sorted((r["arm"], r["metrics"]["accuracy"]) for r in rows) == [("a", 0.3), ("b", 0.2)]


def test_table_formats_metrics():
    r = ledger.row("e", "a|b", ledger.cond(index="x"), {"n": 3, "accuracy": 0.5, "accuracy_ci95": [0.4, 0.6]},
                   dataset="d", split="s")
    text = ledger.table([r])
    assert "50.0%" in text and "40.0–60.0" in text and "a/b" in text


def test_every_abcd_arm_states_its_conditions():
    from bench.run_abcd import arm_conditions

    for name in ("A:raw->raw", "B:summary->summary@1500", "D2:fused+rerank->raw", "ref:win10", "ref:win5@1500"):
        c = arm_conditions(name)
        assert set(ledger.CONDITION_KEYS) <= set(c)
    assert arm_conditions("A:raw->raw@1500")["filter"] == "否"
    assert arm_conditions("A:raw->raw")["filter"] == "是"


def test_tokens_split_into_filter_answer_judge_and_other():
    t = {"筛选": {"prompt": 1000, "completion": 200}, "回答": {"prompt": 3000, "completion": 1000},
         "判官": {"prompt": 500, "completion": 100}, "上色": {"prompt": 9000, "completion": 4000}}
    r = ledger.row("e", "a", ledger.cond(), {}, dataset="d", split="s", tokens=t)
    assert ledger.tok(r, "筛选") == "1k/0k" and ledger.tok(r, "回答") == "3k/1k" and ledger.tok(r, None) == "9k/4k"
    assert ledger.tok(ledger.row("e", "a", ledger.cond(), {}, dataset="d", split="s"), "回答") == ""


def test_for_arm_strips_the_arm_and_keeps_judge_sub_roles():
    from bench.ledger_backfill import for_arm, shared

    by_role = {"筛选|A": 1, "回答|A": 2, "回答|B": 3, "判官|梗解释|A": 4, "出题": 5, "写词条|统计初筛": 6}
    assert for_arm(by_role, "A") == {"筛选": 1, "回答": 2, "判官|梗解释": 4}
    assert shared(by_role) == {"出题": 5, "写词条|统计初筛": 6}


def test_packing_arms_state_conditions():
    from bench.run_abcd import arm_conditions

    for name in ("E1:rrf4@1500", "E2:rr2@1500", "E3:reserve4@1500", "E4:aware2@1500"):
        c = arm_conditions(name)
        assert c["budget_chars"] == 1500 and c["filter"] == "否" and c["top_k"] == 10
    assert "向量" in arm_conditions("E3:reserve4@1500")["index"] or "四路" in arm_conditions("E3:reserve4@1500")["index"]


def test_depth_arms_state_their_depth():
    from bench.run_abcd import arm_conditions

    c = arm_conditions("K5:rrf4@1500")
    assert c["top_k"] == 5 and c["budget_chars"] == 1500 and c["filter"] == "否"
    assert arm_conditions("E1:rrf4@1500")["top_k"] == 10
