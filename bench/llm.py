"""Batch model calls through the local gateway proxy: resumable, with tokens recorded per call."""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench import usage

DEFAULT_MODEL = "gemini-3.8-flash-high"
# A different family from the models under test, as the benchmark plan requires.
JUDGE_MODEL = "gpt-6.1-sol"
ENDPOINT = os.environ.get("QQBOT_BENCH_LLM_URL", "http://127.0.0.1:8317/v1/chat/completions")
GATEWAY_CONFIG = Path(os.environ.get("QQBOT_BENCH_GATEWAY_CONFIG", Path.home() / "model-gateway" / "config.yaml"))
RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def api_key() -> str:
    """From the environment, else the first entry of api-keys in the gateway config."""
    key = os.environ.get("QQBOT_BENCH_LLM_KEY", "")
    if key:
        return key
    in_keys = False
    for line in GATEWAY_CONFIG.read_text(encoding="utf-8").splitlines():
        if re.match(r"^api-keys\s*:", line):
            in_keys = True
        elif in_keys:
            match = re.match(r"^\s*-\s*[\"']?([^\"'\s#]+)", line)
            if match:
                return match.group(1)
            if line.strip() and not line.startswith((" ", "\t", "#")):
                break
    raise RuntimeError("no API key found for the local proxy")


class BatchLLM:
    def __init__(self, cache_path: Path, model: str = DEFAULT_MODEL, workers: int = 4, timeout: int = 300):
        self.cache_path = cache_path
        self.model = model
        self.workers = workers
        self.timeout = timeout
        self.lock = threading.Lock()
        self.cache: dict[str, dict] = {}
        self.errors: Counter = Counter()
        if cache_path.exists():
            with cache_path.open(encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line)
                    self.cache[row["key"]] = row

    def _key(self, system: str, prompt: str) -> str:
        return hashlib.sha256(f"{self.model}\0{system}\0{prompt}".encode()).hexdigest()

    def _request(self, system: str, prompt: str) -> dict:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        }).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key()}"}
        request = urllib.request.Request(ENDPOINT, body, headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def call(self, system: str, prompt: str, role: str = "") -> str:
        key = self._key(system, prompt)
        if key in self.cache:
            row = self.cache[key]
            usage.record(role, self.model, key, False, row.get("prompt_tokens", 0), row.get("completion_tokens", 0))
            return row["text"]
        delay, error, empties = 5.0, "", 0
        for _ in range(6):
            try:
                data = self._request(system, prompt)
                # A blocked prompt comes back with no choices at all.
                choices = data.get("choices") or [{}]
                text = (choices[0].get("message") or {}).get("content") or ""
                if text:
                    break
                # An empty answer is usually a content block; retrying more will not change it.
                empties += 1
                if empties >= 2:
                    break
                error = "empty answer"
            except urllib.error.HTTPError as e:
                error = f"http {e.code}"
                if e.code not in RETRYABLE:
                    raise RuntimeError(error) from None
            except (urllib.error.URLError, TimeoutError, http.client.HTTPException, ConnectionError, KeyError, IndexError,
                    json.JSONDecodeError) as e:
                error = type(e).__name__
            with self.lock:
                self.errors[error] += 1
            time.sleep(delay)
            delay = min(delay * 2, 120.0)
        else:
            raise RuntimeError(error)
        spent = data.get("usage", {})
        row = {
            "key": key,
            "text": text,
            "empty": not text,
            "model": data.get("model", self.model),
            "prompt_tokens": spent.get("prompt_tokens", 0),
            "completion_tokens": spent.get("completion_tokens", 0),
        }
        with self.lock:
            self.cache[key] = row
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with self.cache_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        usage.record(role, self.model, key, True, row["prompt_tokens"], row["completion_tokens"])
        return text

    def map(self, system: str, prompts: list[str], role: str = "") -> list[str | None]:
        def one(prompt: str) -> str | None:
            try:
                return self.call(system, prompt, role)
            except RuntimeError:
                return None

        with ThreadPoolExecutor(self.workers) as ex:
            return list(ex.map(one, prompts))

    @property
    def tokens(self) -> dict:
        rows = self.cache.values()
        return {
            "calls": len(self.cache),
            "empty_answers": sum(bool(r.get("empty")) for r in rows),
            "retried_errors": dict(self.errors),
            "prompt": sum(r.get("prompt_tokens", 0) for r in rows),
            "completion": sum(r.get("completion_tokens", 0) for r in rows),
        }
