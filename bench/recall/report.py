"""Aggregates that need no model, and the ledger rows of the recall labelling. DEV only.

  reply lag   how far back quote-replies reach (the exact trace of a member going back to an
              earlier message), from the export's reply_to field
  ledger      one row per stage, group and model, from the summary files of run_label / run_link;
              with --impressions, the rows of the impression work instead (run_impress, impress_probe,
              impress_check, run_policy, pair_pack), so the labelling rows keep their date

    python -m bench.recall.report --group 4fe395 --name DEV-1 --out <runs>/real-dev --ledger <runs>/ledger.jsonl [--impressions]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from bench import ledger, realdata
from bench.recall import markers
from bench.recall.run_label import AFTER, BEFORE
from bench.recall.run_link import BLOCK_CHARS, CANDIDATES
from bench.schema import Visibility
from bench.tasks.real_tasks import clean_messages

REPLY_BUCKETS = ((60, "1 分钟内"), (600, "1 到 10 分钟"), (3600, "10 分钟到 1 小时"), (86400, "1 小时到 1 天"),
                 (7 * 86400, "1 天到 1 周"), (30 * 86400, "1 周到 1 个月"), (float("inf"), "1 个月以上"))


def reply_lag(messages) -> dict:
    by_id = {m.msg_id: m for m in messages}
    programs = markers.program_like(messages)
    c, lags, missing, own = Counter(), [], 0, 0
    for m in messages:
        if not m.reply_to or m.author in programs:
            continue
        o = by_id.get(m.reply_to)
        if o is None:
            missing += 1  # the quoted message is outside the export or was removed
            continue
        lag = m.timestamp - o.timestamp
        lags.append(lag)
        own += o.author == m.author
        c[next(name for limit, name in REPLY_BUCKETS if lag < limit)] += 1
    lags.sort()
    return {"messages": len(messages), "replies": len(lags) + missing, "target_missing": missing, "quotes_own_message": own,
            "lag": {name: c[name] for _, name in REPLY_BUCKETS},
            "lag_minutes_quantiles": {str(q): round(lags[int(q * (len(lags) - 1))] / 60, 1) for q in (0.5, 0.9, 0.99)} if lags else {}}


def rows(name: str, out: Path) -> list[dict]:
    made = []
    s1 = json.loads((out / "recall.label.summary.json").read_text(encoding="utf-8"))
    keep = {k: v for k, v in s1.items() if k not in ("group", "model", "tokens", "context")}
    made.append(ledger.row(
        f"回忆标注 一阶段：群友的回忆语句（{name}）", s1["model"],
        ledger.cond(index="正则初筛（六类标记）", feed=f"目标消息前 {BEFORE} 条后 {AFTER} 条，脱敏", model_main=s1["model"]),
        keep, dataset="QQ", split=name, tokens=s1["tokens"],
        note="模型标注，未经人工核对；deepseek-chat 实际由 deepseek-flash 应答。程序账号的消息不计。"))
    for path in sorted(out.glob("recall.link.*.summary.json")):
        s2 = json.loads(path.read_text(encoding="utf-8"))
        if s2.get("candidates_per_recall") is None or "block_chars" not in s2:
            continue  # an earlier version of stage 2
        keep = {k: v for k, v in s2.items() if k not in ("group", "model", "tokens", "candidates_per_recall", "block_chars")}
        made.append(ledger.row(
            f"回忆标注 二阶段：回忆对原文（{name}）", s2["model"],
            ledger.cond(index="冻结检索 V2 四路，全局 RRF，不打包", chunking="颜色块", top_k=CANDIDATES,
                        feed=f"候选块逐行编号，每块 {BLOCK_CHARS} 字内", model_main="-", judge=s2["model"]),
            keep, dataset="QQ", split=name,
            # with --compare the summary also carries the other judge's calls; they belong to its own row
            tokens={role: v for role, v in s2["tokens"].items() if "对原文" not in role or role.endswith(s2["model"])},
            note="模型判定原文所在行并对比，未经人工核对；两个模型选中同一行的比例低，数字只作线索。"))
    old = out / "recall.link.summary.v1-quote.json"
    if old.exists():  # first version: the judge quoted the original instead of naming a line; kept for its cost
        s0 = json.loads(old.read_text(encoding="utf-8"))
        made.append(ledger.row(
            f"回忆标注 二阶段：回忆对原文（{name}）", f"{s0['model']}（引句版，作废）",
            ledger.cond(index="冻结检索 V2 四路，全局 RRF，不打包", chunking="颜色块", top_k=CANDIDATES,
                        feed="候选块每块 600 字内，模型照抄原话", model_main="-", judge=s0["model"]),
            {k: s0.get(k) for k in ("group_chat_recalls", "judged", "linked")}, dataset="QQ", split=name, status="void",
            tokens={role: v for role, v in s0["tokens"].items() if "对原文" in role},
            note="抽查发现选中的常是话题相近的另一段，照抄的原话对不上具体消息；改为逐行编号后重跑。含程序账号的回忆。"))
    return made


def impression_rows(name: str, out: Path) -> list[dict]:
    load = lambda path: json.loads(path.read_text(encoding="utf-8"))
    drop = ("group", "model", "variant", "tokens", "chunk", "day_starts", "impressions_from", "answer_model", "me", "depth")
    made = []
    for path in sorted(out.glob("recall.impress.*.summary.json")):
        if ".smoke." in path.name:
            continue  # its calls are in the cache of the full run and counted there
        s = load(path)
        arm = s["model"] + ("（去掉「深的很少」一句）" if s.get("variant") == "nocaution" else "")
        made.append(ledger.row(
            f"印象形成：按时间顺序回放（{name}）", arm,
            ledger.cond(chunking=f"按天（{s['day_starts']} 点起算），每次 {s['chunk']} 条", model_main=s["model"],
                        feed="上一段之后的「这个群平时什么样」+ 当天已留下印象的事 + 逐行编号的聊天，脱敏"),
            {k: v for k, v in s.items() if k not in drop}, dataset="QQ", split=name, tokens=s["tokens"],
            note="模型读后自述会留下什么印象，未与人的记忆对照；只引用行号，引用不存在的行会被丢弃。"))
        tag = path.name[len("recall.impress."):-len(".summary.json")]
        check = out / f"recall.impress_check.{tag}.json"
        if check.exists():
            made.append(ledger.row(
                f"印象形成：和群友后来提起的事对照（{name}）", arm, ledger.cond(index="-", model_main="-"),
                {k: v for k, v in load(check).items() if k not in drop}, dataset="QQ", split=name,
                note="不调模型。被回忆的原文来自二阶段的模型判定（未核对），样本很小，只作线索。"))
        for dry in sorted(out.glob(f"recall.policy2.{tag}.*.summary.json")):
            if "." in dry.name[len(f"recall.policy2.{tag}."):-len(".summary.json")]:
                continue  # belongs to a variant of this set
            d = load(dry)
            made.append(ledger.row(
                f"回忆策略 v2 空跑（{name}）", f"{arm}｜{d['me']}",
                ledger.cond(index="冻结检索 V2 四路，全局 RRF", chunking="颜色块", top_k=d["depth"], feed="按印象定粒度",
                            budget_chars=1500, model_main="-"),
                {k: v for k, v in d.items() if k not in drop}, dataset="QQ", split=name,
                note="不调回答模型，只描述策略；查询向量取自缓存。不是分数：第三个想法不按问答准确率评。"))
        pairs = out / f"recall.pairs.{tag}.summary.json"
        if pairs.exists():
            d = load(pairs)
            made.append(ledger.row(
                f"回忆对比盲评包（{name}）", arm,
                ledger.cond(index="冻结检索 V2 四路，全局 RRF", chunking="颜色块", feed="冻结打包的原文 对 按印象定粒度",
                            budget_chars=1500, model_main=d["answer_model"]),
                {k: v for k, v in d.items() if k not in drop}, dataset="QQ", split=name,
                tokens={role: v for role, v in d["tokens"].items() if role.startswith("回忆对比")},
                note="同一个回答模型、同一句指令，只换记忆部分；这里没有分数，等用户盲评。两套印象共用冻结版一侧的缓存，"
                     "重复的题在两行里都计了 token，新花的看 new_*。"))
    for path in sorted(out.glob("recall.impress_probe.*.summary.json")):
        s = load(path)
        made.append(ledger.row(
            f"印象形成：措辞探查（{name}）", s["model"],
            ledger.cond(chunking="主回放里留下「中」印象的那些段，输入不变", model_main=s["model"], feed="系统提示去掉「深的很少」一句"),
            {k: v for k, v in s.items() if k not in drop}, dataset="QQ", split=name, tokens=s["tokens"],
            note="诊断用，不进策略层。"))
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--group", required=True)
    ap.add_argument("--name", required=True, help="split name, e.g. DEV-1")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ledger", type=Path)
    ap.add_argument("--impressions", action="store_true", help="write the rows of the impression work only")
    args = ap.parse_args()
    if realdata.splits()[args.group] is not Visibility.DEV:
        raise SystemExit("DEV only")
    if not args.impressions:
        lag = reply_lag(clean_messages(realdata.load_group(args.group)))
        (args.out / "recall.reply_lag.json").write_text(json.dumps(lag, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps(lag, ensure_ascii=False))
    if args.ledger:
        made = impression_rows(args.name, args.out) if args.impressions else rows(args.name, args.out)
        ledger.append(args.ledger, made)
        print("ledger rows:", [(r["experiment"], r["arm"]) for r in made])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
