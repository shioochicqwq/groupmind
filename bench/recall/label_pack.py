"""Check pack for the recall labelling: a person re-labels a sample without seeing the model's
answers, and judges every proposed original. Original names; the page stays outside the repo.

Part 1  a sample of stage-1 candidates (recalls of group chat, other recalls, non-recalls), in
        context. The person answers the same questions the model did.
Part 2  every (recall, proposed original) pair from the stage-2 judges, shown without saying which
        judge proposed it: is this the original, is the content the same, is the speaker right.

    python -m bench.recall.label_pack --group 4fe395 --name DEV-1 --run <runs>/real-dev --out <labels>/recall-r1/dev1.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

from bench import labelkit, realdata
from bench.events.label_pack import mask
from bench.recall.run_label import AFTER, BEFORE, TZ
from bench.sanitize import is_sensitive
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages

AROUND = 5  # messages shown on each side of a proposed original
SAMPLE = (("群内聊天", 12), ("其他回忆", 12), ("不是回忆", 8))


def line(m, mark: bool = False) -> list:
    t = dt.datetime.fromtimestamp(m.timestamp, TZ).strftime("%m-%d %H:%M")
    body = "（这条已隐藏）" if is_sensitive(m.content) else mask(m.content)[:300] or ("[图片或文件]" if m.media else "")
    return [t, m.nickname_at_time or "?", body, int(mark)]


def window(messages, pos: int, before: int, after: int) -> list:
    return [line(messages[i], i == pos) for i in range(max(0, pos - before), min(len(messages), pos + after + 1))
            if messages[i].content or messages[i].media or i == pos]


def span(seconds: float) -> str:
    for size, unit in ((86400, "天"), (3600, "小时"), (60, "分钟")):
        if seconds >= size:
            return f"{seconds / size:.0f} {unit}"
    return "不到 1 分钟"


def sample(rows: list[dict], rng: random.Random) -> list[dict]:
    def kind(r):
        if not r["label"]["recall"]:
            return "不是回忆"
        return "群内聊天" if r["label"]["target"] == "群内聊天" else "其他回忆"
    out = []
    for name, n in SAMPLE:
        part = [r for r in rows if kind(r) == name]
        out += rng.sample(part, min(n, len(part)))
    rng.shuffle(out)  # the order must not give the model's answer away
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--name", required=True, help="split name shown on the page, e.g. DEV-1")
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    messages = clean_messages(realdata.load_group(args.group))
    pos_of = {m.msg_id: i for i, m in enumerate(messages)}
    rng = random.Random(0)

    labelled = [r for r in map(json.loads, (args.run / "recall.labels.jsonl").open(encoding="utf-8"))
                if r["label"] and not r.get("program")]
    labels = [{"id": f"l:{r['msg_id']}", "lines": window(messages, pos_of[r["msg_id"]], BEFORE, AFTER)}
              for r in sample(labelled, rng)]

    pairs: dict[tuple[str, str], dict] = {}
    for path in sorted(args.run.glob("recall.links.deepseek-*.jsonl")):
        for r in map(json.loads, path.open(encoding="utf-8")):
            if r.get("origin_msg_id"):
                pairs.setdefault((r["msg_id"], r["origin_msg_id"]), r)
    links = []
    for (rid, oid), r in pairs.items():
        links.append({"id": f"k:{rid}:{oid}", "recall": window(messages, pos_of[rid], BEFORE, AFTER),
                      "origin": window(messages, pos_of[oid], AROUND, AROUND),
                      "gap": span(messages[pos_of[rid]].timestamp - messages[pos_of[oid]].timestamp)})
    rng.shuffle(links)

    data = {"pack": f"recall-r1-{args.name.lower()}", "group": args.name, "labels": labels, "links": links}
    labelkit.build("recall_round1", f"回忆标注核对 · {args.name}", data, args.out)
    print(args.out, len(labels), "labels", len(links), "pairs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
