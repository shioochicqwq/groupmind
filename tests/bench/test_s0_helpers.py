from bench.run_s0 import final_of, is_refusal, subset


def test_final_of_prefers_final_line():
    assert final_of("想一想\nFinal: 火锅") == "火锅"
    assert final_of("想一想\nfinal：2") == "2"
    assert final_of("没有格式") == "没有格式"
    assert final_of(None) == ""


def test_refusal_detection():
    assert is_refusal("没有记录") and not is_refusal("在学校门口")


def test_subset_keeps_only_named_cases():
    assert list(subset({"per_case": {"a": 1, "b": 2}}, {"b"})["per_case"]) == ["b"]
