from bench.run_term_baseline import verdict


def test_verdict_parsing():
    assert verdict("理由\nFinal: Correct") == "correct"
    assert verdict("Final: Incorrect") == "incorrect"
    assert verdict("Final: Unknown") == "unknown"
    assert verdict("") == "incorrect"
