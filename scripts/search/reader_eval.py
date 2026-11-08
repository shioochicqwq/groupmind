"""Can a model pull exact original text through web_reader? (search module, 2026-11-07)

Cases (reader_cases.json): "direct" gives the page that holds the text; "deep" gives only the
site's entry page, so the model has to follow links. Golds were checked against the raw sources.

  ceiling  no model: follow the links web_reader returns (same site, up to 2 hops, at most
           --max-pages pages per case) and report whether the gold text is reachable at all.
  model    a tool loop on an OpenAI-compatible endpoint: the model gets one tool, web_read(url,
           offset), and must answer with the original text. Scored on: gold found in the answer;
           quoted text present in some page it actually read (otherwise it is fabricated);
           "could not read" admitted when nothing was found.

The API key is read from --key-file and never printed. Pages are public; nothing from group chats.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urldefrag, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backends  # noqa: E402

HERE = Path(__file__).parent
SYSTEM = """你可以用工具 web_read 读取网页：它返回标题、正文（分段，more=true 时用 offset 续读）和页面上的链接。
任务是找到问题要的那段原文，一字不改地给出。需要时沿链接继续读。
只有当你确认这段原文出现在你收到过的 content 里时，才能写「原文：」；没看到就用 offset 续读，或换别的链接。
不要凭记忆作答，不要改写，不要用没读到的内容填空。
最后一行只写：原文：<原文>；如果读不到或找不到，最后一行写：无法获取：<原因>"""
TOOL = {"type": "function", "function": {
    "name": "web_read", "description": "Read a public web page. Returns title, a chunk of main text, whether more text follows, and links on the page.",
    "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "offset": {"type": "integer", "default": 0}},
                   "required": ["url"]}}}


def norm(s: str) -> str:
    """Whitespace collapsed, Markdown emphasis and code marks and backslash escapes removed, lower case."""
    s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)   # Markdown links and images -> their text
    s = re.sub(r"[*`_\\#]", "", s)
    return re.sub(r"\s+", " ", s).replace(" .", ".").replace(" ,", ",").strip().lower()


BACKEND = "web_reader"


def read(url: str, offset: int = 0, links_offset: int = 0, links_page: int = 150) -> dict:
    return backends.read(BACKEND, url, offset, links_offset, links_page)


def full_text(url: str) -> tuple[str, list, str | None]:
    """Whole page text plus every link on it (the ceiling test is about reachability, not pagination)."""
    parts, links, off = [], None, 0
    while True:
        d = read(url, off, 0, 100_000)
        if not d["ok"]:
            return "".join(parts), links or [], d["error"]
        parts.append(d["text"])
        links = links if links is not None else d["links"]
        if not d.get("more"):
            return "".join(parts), links, None
        off = d["end"]


def ceiling(case: dict, max_pages: int) -> dict:
    host = urlsplit(case["url"]).netloc
    seen, frontier, pages, found_at, errors = set(), [(case["url"], 0)], 0, None, []
    while frontier and pages < max_pages and not found_at:
        url, depth = frontier.pop(0)
        url = urldefrag(url)[0]
        if url in seen:
            continue
        seen.add(url)
        text, links, err = full_text(url)
        pages += 1
        if err:
            errors.append(f"{url} -> {err}")
            continue
        if case["gold"] and norm(case["gold"]) in norm(text):
            found_at = {"url": url, "depth": depth}
            break
        if depth < 2:
            for _label, href in links:
                if urlsplit(href).netloc == host:
                    frontier.append((href, depth + 1))
    return {"reachable": bool(found_at), "found_at": found_at, "pages_read": pages, "errors": errors[:3]}


def chat(endpoint: str, key: str, model: str, messages: list) -> dict:
    body = json.dumps({"model": model, "messages": messages, "tools": [TOOL], "temperature": 0}).encode()
    req = urllib.request.Request(endpoint, body, {"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def run_model(case: dict, endpoint: str, key: str, model: str, max_steps: int) -> dict:
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"网址：{case['url']}\n问题：{case['question']}"}]
    trace, read_texts, usage = [], [], {"prompt": 0, "completion": 0}
    answer = ""
    for _ in range(max_steps):
        data = chat(endpoint, key, model, messages)
        u = data.get("usage", {})
        usage["prompt"] += u.get("prompt_tokens", 0)
        usage["completion"] += u.get("completion_tokens", 0)
        msg = data["choices"][0]["message"]
        messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
        calls = msg.get("tool_calls") or []
        if not calls:
            answer = msg.get("content") or ""
            break
        for c in calls:
            args = json.loads(c["function"]["arguments"] or "{}")
            links_offset = int(args.get("links_offset", 0) or 0)
            d = read(args.get("url", ""), int(args.get("offset", 0) or 0), links_offset)
            trace.append({"url": args.get("url"), "offset": args.get("offset", 0), "links_offset": links_offset, "ok": d["ok"],
                          "chars": len(d.get("text", "")), "error": d.get("error")})
            if d["ok"]:
                read_texts.append(d["text"])
                payload = {k: d[k] for k in ("url", "title", "start", "end", "more", "text", "links_total", "links_more", "links_next")}
                payload["links"] = [f"{label[:60]} | {href}" for label, href in d["links"]]
            else:
                payload = {"error": d["error"]}
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": json.dumps(payload, ensure_ascii=False)})
    last = (answer.strip().splitlines() or [""])[-1]
    quoted = last.split("原文：", 1)[1].strip() if "原文：" in last else ""
    admitted = "无法获取" in last
    seen = norm(" ".join(read_texts))
    coverage = quote_coverage(quoted, seen)
    return {
        "answer_last_line": last[:300], "steps": len(trace), "trace": trace, "usage": usage,
        "correct": bool(case["gold"]) and norm(case["gold"]) in norm(answer),
        "quote_in_pages": bool(quoted) and coverage >= FABRICATED_COVERAGE,
        # A model may join list items or normalise punctuation; only text that is mostly absent
        # from the pages it read counts as fabricated.
        "fabricated": bool(quoted) and coverage < FABRICATED_COVERAGE,
        "quote_coverage": coverage,
        "admitted_failure": admitted,
    }


FABRICATED_COVERAGE = 0.5


def _chars(text: str) -> str:
    """Lower-case letters, digits and CJK only; punctuation and whitespace are ignored."""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", norm(text))


def quote_coverage(quoted: str, seen: str) -> float:
    """Share of 5-character shingles of the quote that occur in the text the model actually read.

    Character shingles rather than word shingles: a model may join list items, change
    ``True:`` to ``true :`` or insert/remove spaces, and none of that is fabrication.
    """
    q, page = _chars(quoted), _chars(seen)
    if not q:
        return 0.0
    if len(q) <= 5:
        return 1.0 if q in page else 0.0
    shingles = {q[i : i + 5] for i in range(len(q) - 4)}
    return sum(s in page for s in shingles) / len(shingles)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("ceiling", "model"))
    ap.add_argument("--cases", type=Path, default=HERE / "reader_cases.json")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-pages", type=int, default=40)
    ap.add_argument("--endpoint", default="https://api.deepseek.com/chat/completions")
    ap.add_argument("--model", default="deepseek-chat")
    ap.add_argument("--key-file", type=Path)
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--backend", choices=sorted(backends.BACKENDS), default="web_reader")
    args = ap.parse_args()
    global BACKEND
    BACKEND = args.backend
    cases = json.loads(args.cases.read_text(encoding="utf-8"))
    key = args.key_file.read_text(encoding="utf-8").strip() if args.key_file else ""
    if args.mode == "model" and not key:
        raise SystemExit("--key-file is required for model mode")
    rows = []
    for c in cases:
        t = time.time()
        r = ceiling(c, args.max_pages) if args.mode == "ceiling" else run_model(c, args.endpoint, key, args.model, args.max_steps)
        rows.append({"id": c["id"], "kind": c["kind"], "sec": round(time.time() - t, 1), **r})
        print(json.dumps({k: v for k, v in rows[-1].items() if k != "trace"}, ensure_ascii=False), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"mode": args.mode, "backend": args.backend, "model": args.model if args.mode == "model" else None,
                                    "when": time.strftime("%Y-%m-%d %H:%M"), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
