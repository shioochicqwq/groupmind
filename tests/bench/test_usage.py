from bench import llm, usage
from tests.bench.test_llm import FakeResponse


def test_usage_splits_roles_and_separates_new_from_cached(tmp_path, monkeypatch):
    usage.reset()
    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "secret-value")
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda r, timeout: FakeResponse(
        {"choices": [{"message": {"content": "x"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}))
    client = llm.BatchLLM(tmp_path / "c.jsonl")
    client.map("s", ["a", "b"], role="筛选")
    client.call("s", "a", role="筛选")
    client.call("s", "a", role="回答")
    got = usage.summary()
    assert got["筛选"]["calls"] == 3 and got["筛选"]["distinct"] == 2
    assert got["筛选"]["prompt"] == 20 and got["筛选"]["new_prompt"] == 20
    assert got["回答"]["prompt"] == 10 and got["回答"]["new_calls"] == 0
    usage.reset()
    llm.BatchLLM(tmp_path / "c.jsonl").call("s", "b", role="上色")
    assert usage.summary()["上色"] == {
        "calls": 1, "distinct": 1, "prompt": 10, "completion": 2, "new_calls": 0, "new_prompt": 0,
        "new_completion": 0, "models": [llm.DEFAULT_MODEL]}
