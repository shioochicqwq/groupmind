import json

from bench import llm


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, *args):
        return json.dumps(self.payload).encode()


def test_key_comes_from_env_then_config(tmp_path, monkeypatch):
    config = tmp_path / "c.yaml"
    config.write_text('port: 1\napi-keys:\n  - "from-config"\n  - other\nhost: x\n', encoding="utf-8")
    monkeypatch.setattr(llm, "GATEWAY_CONFIG", config)
    monkeypatch.delenv("QQBOT_BENCH_LLM_KEY", raising=False)
    assert llm.api_key() == "from-config"
    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "from-env")
    assert llm.api_key() == "from-env"


def test_call_is_cached_on_disk(tmp_path, monkeypatch):
    calls = []

    def fake_open(request, timeout):
        calls.append(request)
        return FakeResponse({"choices": [{"message": {"content": "hi"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "secret-value")
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_open)
    cache = tmp_path / "c.jsonl"
    client = llm.BatchLLM(cache)
    assert client.call("s", "p") == "hi" and client.call("s", "p") == "hi"
    assert len(calls) == 1 and client.tokens == {
        "calls": 1, "empty_answers": 0, "retried_errors": {}, "prompt": 3, "completion": 1}
    assert llm.BatchLLM(cache).call("s", "p") == "hi" and len(calls) == 1
    assert "secret-value" not in cache.read_text(encoding="utf-8")


def test_permanent_error_becomes_none_and_is_not_cached(tmp_path, monkeypatch):
    def fake_open(request, timeout):
        raise llm.urllib.error.HTTPError("u", 400, "bad", {}, None)

    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "secret-value")
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_open)
    cache = tmp_path / "c.jsonl"
    assert llm.BatchLLM(cache).map("s", ["p"]) == [None]
    assert not cache.exists()


def test_empty_answer_is_tried_twice_then_cached_as_empty(tmp_path, monkeypatch):
    calls = []

    def fake_open(request, timeout):
        calls.append(1)
        return FakeResponse({"choices": [{"message": {"content": ""}}], "usage": {}})

    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "secret-value")
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    client = llm.BatchLLM(tmp_path / "c.jsonl")
    assert client.call("s", "p") == "" and len(calls) == 2
    assert client.tokens["empty_answers"] == 1


def test_blocked_response_without_choices_counts_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("QQBOT_BENCH_LLM_KEY", "secret-value")
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda r, timeout: FakeResponse({"choices": []}))
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    client = llm.BatchLLM(tmp_path / "c.jsonl")
    assert client.call("s", "p") == "" and client.tokens["empty_answers"] == 1
