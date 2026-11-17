"""Stickers seen apart from the group's session, so they never hold it up.

A sticker in a group message is shown to the session as "[表情]" until it is known what it means. As soon as the message
arrives, a call of its own (a vision model, one image, one short question) asks what the sticker expresses. The answer is
kept with the message in the store, marked as seen by the machine, and reaches the session the quickest way it can: in the
message itself when the session has not read it yet, otherwise as a line in its next turn. Stickers are sent again and
again, so answers are cached by the picture's content and the same sticker costs one call ever.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)
QUESTION = ("这是 QQ 群聊里的一个表情包。用一句话说它表达的情绪或意思（例如：翻白眼，表示无语；猫猫探头，表示围观），"
            "不要描述画面细节，只输出这一句。")


class Stickers:
    def __init__(self, cache_file: Path, model: str, base_url: str, api_key: str, parallel: int = 2) -> None:
        self.cache_file, self.model, self.base_url, self.api_key = Path(cache_file), model, base_url.rstrip("/"), api_key
        try:
            self.cache: dict[str, str] = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}
        self.slots = asyncio.Semaphore(parallel)
        self.used: list[dict] = []   # model calls since last read, for the usage log

    def _ask(self, b64: str, mime: str) -> tuple[str, dict]:
        body = {"model": self.model, "max_tokens": 600, "messages": [{"role": "user", "content": [
            {"type": "text", "text": QUESTION}, {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]}
        req = urllib.request.Request(self.base_url + "/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
        text = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return text.strip().splitlines()[0].strip().rstrip("。")[:60] if text.strip() else "", d.get("usage") or {}

    async def meaning(self, picture: tuple[str, str]) -> str:
        """What a sticker expresses, from the cache or one model call. Empty when it could not be seen."""
        b64, mime = picture
        key = hashlib.sha256(base64.b64decode(b64)).hexdigest()
        if key in self.cache:
            return self.cache[key]
        async with self.slots:
            if key in self.cache:   # another call for the same sticker finished while this one waited
                return self.cache[key]
            t0 = time.monotonic()
            try:
                text, usage = await asyncio.to_thread(self._ask, b64, mime)
            except (OSError, ValueError) as e:
                log.info("sticker not seen: %s", type(e).__name__)
                return ""
            self.used.append({"calls": 1, "prompt": int(usage.get("prompt_tokens") or 0), "completion": int(usage.get("completion_tokens") or 0),
                              "seconds": round(time.monotonic() - t0, 1)})
            if text:
                self.cache[key] = text
                tmp = self.cache_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.cache, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.cache_file)
            return text
