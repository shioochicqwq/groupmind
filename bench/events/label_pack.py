"""Event labeling pack, round 1: rate evenings of a DEV group (original names; output outside the repo).

Unit: an evening is 18:00 to 06:00 the next morning, Beijing time (UTC+8), with at least
`min_msgs` messages. Each card shows the evening as its B blocks in time order (colour summary,
time span, messages expandable), plus any uncoloured messages. No structural feature is shown,
so the ratings do not lean on the measures the event layer will be tested with. The pack is
named after the output file, so a new file name starts with empty progress.

    python -m bench.events.label_pack --group 4fe395 --run <runs>/real-dev --out <labels>/events-r1/label-events-r1-dev1-v2.html
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

from bench import labelkit, realdata
from bench.events.build import primary_color
from bench.sanitize import _BANK, _EMAIL, _ID_CARD, _LONG_NUM, _PHONE, _URL, is_sensitive
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages

TZ = dt.timezone(dt.timedelta(hours=8))


def evening_of(ts: float) -> dt.date | None:
    t = dt.datetime.fromtimestamp(ts, TZ)
    if t.hour >= 18 or t.hour < 6:
        return (t - dt.timedelta(hours=6)).date()
    return None


def mask(text: str) -> str:
    for rx, rep in ((_URL, "<链接>"), (_EMAIL, "<邮箱>"), (_ID_CARD, "<证件号>"), (_BANK, "<长数字>"),
                    (_PHONE, "<电话>"), (_LONG_NUM, "<长数字>")):
        text = rx.sub(rep, text)
    return text


def line(m) -> list:
    t = dt.datetime.fromtimestamp(m.timestamp, TZ).strftime("%H:%M")
    if is_sensitive(m.content):
        body = "（这条已隐藏）"
    else:
        body = mask(m.content)[:300] or ("[图片或文件]" if m.media else "")
    return [t, m.nickname_at_time or "?", body]


def evenings(messages, colors, min_msgs: int) -> list[dict]:
    color_of = primary_color(colors)
    summary = {c["color_id"]: c.get("summary", "") for c in colors}
    by_day = defaultdict(list)
    for m in messages:
        d = evening_of(m.timestamp)
        if d:
            by_day[d].append(m)
    out = []
    for d, part in sorted(by_day.items()):
        if len(part) < min_msgs:
            continue
        groups: dict[str, list] = defaultdict(list)
        order = {m.msg_id: k for k, m in enumerate(part)}
        for m in part:
            groups[color_of.get(m.msg_id, "")].append(m)
        segs = []
        for cid, ms in sorted(groups.items(), key=lambda kv: kv[1][0].timestamp):
            segs.append({"block_id": cid, "summary": summary.get(cid, "") if cid else "（没有上色的消息）",
                         "start": line(ms[0])[0], "end": line(ms[-1])[0], "n": len(ms), "lines": [line(m) + [order[m.msg_id]] for m in ms]})
        wd = "一二三四五六日"[d.weekday()]
        out.append({"id": f"ev:{d.isoformat()}", "date": d.isoformat(), "label": f"{d.month} 月 {d.day} 日（周{wd}）晚上",
                    "n": len(part), "segments": segs})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--name", required=True, help="split name shown on the page, e.g. DEV-1")
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--colors", default="colors.gemini-3.8-flash-high.jsonl")
    ap.add_argument("--min-msgs", type=int, default=100)
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    msgs = clean_messages(realdata.load_group(args.group))
    colors = [json.loads(x) for x in (args.run / args.colors).open(encoding="utf-8")]
    items = evenings(msgs, colors, args.min_msgs)
    data = {"pack": args.out.stem.removeprefix("label-"), "group": args.name, "min_msgs": args.min_msgs, "evenings": items}
    labelkit.build("events_round1", f"事件打标 · {args.name}", data, args.out)
    print(args.out, len(items), "evenings", sum(e["n"] for e in items), "messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
