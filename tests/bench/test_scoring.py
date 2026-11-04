from bench import scoring


def test_three_state_reports_both_accuracies_and_empty_rate():
    rows = [
        {"id": "a", "visible": True, "answer": "x", "correct": True},
        {"id": "b", "visible": True, "answer": "y", "correct": False},
        {"id": "c", "visible": True, "answer": "", "correct": False},
        {"id": "a", "visible": False, "answer": "没有记录", "refused": True},
        {"id": "b", "visible": False, "answer": "", "refused": False},
    ]
    m = scoring.three_state(rows)
    assert m["n"] == 3 and m["n_empty"] == 1
    assert abs(m["accuracy"] - 1 / 3) < 1e-3 and m["accuracy_effective"] == 0.5
    assert m["refusal_when_absent"] == 0.5 and m["refusal_effective"] == 1.0


def test_paired_effective_uses_questions_both_arms_answered():
    a = [{"id": "a", "visible": True, "answer": "x", "correct": False},
         {"id": "b", "visible": True, "answer": "", "correct": False}]
    b = [{"id": "a", "visible": True, "answer": "x", "correct": True},
         {"id": "b", "visible": True, "answer": "y", "correct": True}]
    d = scoring.paired(a, b)
    assert d["end_to_end"]["n"] == 2 and d["end_to_end"]["delta"] == 1.0
    assert d["effective"]["n"] == 1
