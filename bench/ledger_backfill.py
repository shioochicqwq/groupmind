"""Turn the result files of each experiment into ledger rows with stated conditions."""
from __future__ import annotations

import json
import time
from pathlib import Path

from bench.ledger import cond, fingerprint, row
from bench.rawlog import arm_file

SPLIT = {"4fe395": "DEV-1", "ed14b7": "DEV-2"}
GEMINI = "gemini-3.8-flash-high"
GPT = "gpt-6.1-sol"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def usage_of(folder: Path, name: str) -> dict:
    data = _load(folder / f"usage.{name}.json")
    return data["by_role"] if data else {}


def for_arm(by_role: dict, arm: str) -> dict:
    """Roles of one arm, named role|arm in the usage log, with the arm part dropped."""
    out = {}
    for role, v in by_role.items():
        parts = role.split("|")
        if len(parts) >= 2 and parts[-1] == arm:
            out["|".join(parts[:-1])] = v
    return out


SHARED_ROLES = ("上色", "出题", "核题", "梗提取", "写词条", "写参考解释", "向量")


def shared(by_role: dict) -> dict:
    """Work no single arm owns; sub-roles such as 写词条|统计初筛 stay as written."""
    return {r: v for r, v in by_role.items() if r.split("|")[0] in SHARED_ROLES}


def from_cache(path: Path) -> dict:
    """Usage straight from a cache file whose every row has one role."""
    if not path.exists():
        return {}
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]
    return {"calls": len(rows), "distinct": len(rows), "prompt": sum(r.get("prompt_tokens", 0) for r in rows),
            "completion": sum(r.get("completion_tokens", 0) for r in rows),
            "models": sorted({r.get("model", "") for r in rows})}


def cost_rows(folder: Path, split: str) -> list[dict]:
    """Shared work that no single arm owns: coloring, question writing, term extraction."""
    rows = []
    color = from_cache(folder / "color.gemini-3.8-flash-high.cache.jsonl")
    if color:
        rows.append(row(f"成本：上色（{split}）", "上色", cond(model_main=GEMINI), {}, dataset="QQ", split=split,
                        tokens={"上色": color}, when=_when(folder / "color.gemini-3.8-flash-high.cache.jsonl"),
                        raw=raw_ref(folder.parent, folder / "colors.gemini-3.8-flash-high.jsonl")))
    for name, title in (("questions", "出题和核题"), ("s0", "Q2 第一轮"), ("abcd", "主实验"), ("k", "梗表"),
                        ("vector", "向量检索"), ("packing", "打包与保底"), ("depth", "候选深度"), ("embed_qa", "向量配置问答"), ("color_fix", "上色修正")):
        own = shared(usage_of(folder, name))
        if own:
            rows.append(row(f"成本：{title}的共享调用（{split}）", "共享", cond(model_main=GEMINI), {}, dataset="QQ",
                            split=split, tokens=own, when=_when(folder / f"usage.{name}.json"),
                            note="出题、核题、梗提取、写词条等不属于某一组的调用",
                            raw=raw_ref(folder.parent, folder / "s0.main.cache.jsonl")))
    return rows


def with_three_state(original: dict, rows: list[dict]) -> dict:
    """End-to-end accuracy (empty answers count as failures) stays the main number; effective
    accuracy over non-empty answers and the empty rate sit beside it (bench.scoring)."""
    from bench import scoring

    return {**original, **scoring.three_state(rows)}


def raw_ref(runs: Path, path: Path) -> str:
    """Path of a raw record file relative to the runs folder, or empty if it was never written."""
    return str(path.relative_to(runs)) if path.exists() else ""


def _when(path: Path) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))


def gmb(runs: Path) -> list[dict]:
    rows = []
    for name, judge in (("summary.gemini-judge.json", GEMINI), ("summary.json", GPT)):
        path = runs / "gmb-tech" / name
        s = _load(path)
        if not s:
            continue
        metrics = {"n": sum(v["n"] for v in s["per_type"].values()), "accuracy": s["micro"] / 100,
                   "accuracy_ci95": [x / 100 for x in s["ci95"]],
                   **{f"acc_{k}": v["acc"] / 100 for k, v in s["per_type"].items()}}
        gdir = runs / "gmb-tech"
        tokens = {"回答": from_cache(gdir / "agent.cache.jsonl"),
                  "判官": from_cache(gdir / f"judge.{judge}.cache.jsonl")}
        rows.append(row(
            "B1 GroupMemBench", f"BM25 judge={judge}",
            cond(index="单条消息", chunking="单条消息", tokenizer="英文词", top_k=10, filter="否", feed="原文 + 元数据",
                 model_main=s["agent_model"], judge=judge, seed=0),
            metrics, dataset="GroupMemBench", split="Technology", data={"questions": "官方 213 题"},
            note="论文 BM25（GPT-5）46.0%；两行共用同一批回答", when=_when(path), tokens=tokens,
            raw=raw_ref(runs, gdir / "raw" / f"gmb.judge={judge}.jsonl"),
        ))
    rows.append(row(
        "B1 GroupMemBench", "BM25 Claude CLI（作废）",
        cond(index="单条消息", chunking="单条消息", tokenizer="英文词", top_k=10, filter="否", feed="原文 + 元数据",
             model_main="claude-sonnet-5-5", judge="claude-sonnet-5-5", seed=0),
        {"n": 213}, dataset="GroupMemBench", split="Technology", status="void",
        note="大部分调用失败；按用户要求批量任务改用 gateway", when="2026-11-02 13:10",
    ))
    return rows


def q1(runs: Path) -> list[dict]:
    path = runs / "real-dev" / "retrieval.json"
    r = _load(path)
    if not r:
        return []
    rows = []
    chunk_names = {"msg": "单条消息", "win5": "5 条窗口", "win10": "10 条窗口", "win20": "20 条窗口"}
    for key, summary in r["q1"].items():
        tok, chunk, query = key.split("+")
        a = summary["all"]
        rows.append(row(
            "Q1 引用还原（检索）", key,
            cond(index="原文", chunking=chunk_names[chunk], tokenizer=tok, top_k=20, filter="否", feed="-"),
            {"n": a["n"], "R@1": a["R@1"], "R@10": a["R@10"], "R@20": a["R@20"], "MRR": a["MRR"],
             "R@10_1h-1d": summary.get("dist=1h-1d", {}).get("R@10")},
            dataset="QQ", split=SPLIT.get(r["group"], r["group"]), when=_when(path),
            note=f"查询：{'回复本身' if query == 'reply' else '回复 + 前 3 条'}",
            raw=raw_ref(runs, arm_file(runs / "real-dev", "q1", key)),
        ))
    for key, v in r["q3_auc"].items():
        tok, chunk = key.split("+")
        rows.append(row(
            "Q3 BM25 分数判断该不该沉默", key,
            cond(index="原文", chunking=chunk_names[chunk], tokenizer=tok, top_k=1, filter="否", feed="-"),
            {"n": v["n"], "AUC": v["auc"]}, dataset="QQ", split=SPLIT.get(r["group"], r["group"]), when=_when(path),
            note="逐题最高分在同配置的 Q1 原始记录里（top_score）",
            raw=raw_ref(runs, arm_file(runs / "real-dev", "q1", f"{key}+reply")),
        ))
    return rows


Q2_ARMS = {
    "S0": ("颜色摘要", "颜色块", "jieba+习得词"),
    "I1:jieba-only": ("颜色摘要", "颜色块", "jieba"),
    "I1:bigram": ("颜色摘要", "颜色块", "2-gram"),
    "I3:index-raw-block": ("颜色原文块", "颜色块", "jieba+习得词"),
    "I2:win10": ("原文", "10 条窗口", "jieba+习得词"),
    "I2:win5": ("原文", "5 条窗口", "jieba+习得词"),
    "I2:single-msg": ("原文", "单条消息", "jieba+习得词"),
    "reference:bm25-win10": ("原文", "10 条窗口", "jieba"),
}
QA_ARMS = {
    "S0": ("颜色摘要", "是", "摘要", "原文块"),
    "R5:no-filter": ("颜色摘要", "否", "-", "前 5 块原文"),
    "I3:index-raw-block": ("颜色原文块", "是", "原文片段", "原文块"),
    "reference:bm25-win10": ("原文（10 条窗口）", "否", "-", "前 5 个窗口（未去重）"),
}


def name_of(arm) -> str:
    return arm["arm"] if isinstance(arm, dict) else arm


def q2(runs: Path, labels: Path | None) -> list[dict]:
    rows = []
    path = runs / "real-dev" / "s0.json"
    s = _load(path)
    if not s:
        return rows
    split = SPLIT.get(s["group"], s["group"])
    data = {"colors": fingerprint(runs / "real-dev" / "colors.gemini-3.8-flash-high.jsonl"),
            "questions": fingerprint(runs / "real-dev" / "q2_questions.json")}
    for name, summary in s["q2_retrieval"].items():
        index, chunk, tok = Q2_ARMS[name]
        a = summary["all"]
        rows.append(row(
            "Q2 跨周问题（检索）", name,
            cond(index=index, chunking=chunk, tokenizer=tok, top_k=20, filter="否", feed="-", seed=0),
            {"n": a["n"], "R@1": a["R@1"], "R@10": a["R@10"], "R@msgs20": a["R@msgs20"], "R@msgs50": a["R@msgs50"],
             "R@msgs100": a["R@msgs100"], "R@10_low_overlap": summary.get("overlap=low", {}).get("R@10")},
            dataset="QQ", split=split, data=data, when=_when(path),
            raw=raw_ref(runs, arm_file(runs / "real-dev", "q2_retrieval", name)),
        ))
    s0_usage = usage_of(runs / "real-dev", "s0")
    for file, judge in (("s0.gemini-judge.json", GEMINI), ("s0.json", GPT)):
        p = runs / "real-dev" / file
        r = _load(p)
        if not r:
            continue
        for arm in r["qa"]:
            index, flt, view, feed = QA_ARMS[arm["arm"]]
            rows.append(row(
                "Q2 跨周问题（问答）", f"{arm['arm']} judge={judge}",
                cond(index=index, chunking="颜色块" if "颜色" in index else "10 条窗口", tokenizer="jieba" if name_of(arm).startswith("reference") else "jieba+习得词",
                     top_k=10, filter=flt, filter_view=view, feed=feed, model_main=GEMINI, model_filter=GEMINI,
                     judge=judge, seed=0),
                with_three_state({"n": sum(x["visible"] for x in arm["rows"]), **{k: arm[k] for k in (
                    "accuracy", "accuracy_ci95", "refusal_when_absent", "empty_when_present")},
                 "avg_msgs": arm["avg_msgs_injected"]}, arm["rows"]),
                dataset="QQ", split=split, data=data, when=_when(p),
                tokens=for_arm(s0_usage, arm["arm"]) if judge == GPT else {},
                raw=raw_ref(runs, arm_file(runs / "real-dev", "s0", arm["arm"])) if judge == GPT else "",
                note="" if judge == GPT else "gemini 判官的调用未单独记录，回答和筛选与下一组 gpt 判官行共用",
            ))
    merged = _load(labels) if labels else None
    if merged:
        for name, a in merged["arms"].items():
            index, flt, view, feed = QA_ARMS[name]
            rows.append(row(
                "Q2 跨周问题（问答，人工复核）", name,
                cond(index=index, chunking="颜色块" if "颜色" in index else "10 条窗口", tokenizer="jieba" if name.startswith("reference") else "jieba+习得词",
                     top_k=10, filter=flt, filter_view=view, feed=feed, model_main=GEMINI, model_filter=GEMINI,
                     judge=f"人工 3 人，缺省用 {GPT}", seed=0),
                {"n": a["questions"], "accuracy": a["accuracy"], "accuracy_without_awkward": a["accuracy_without_awkward"],
                 "human_verdicts": a["human_verdicts"]},
                dataset="QQ", split=split, data=data, when=_when(labels),
                note=f"判官与人工一致率 {merged['judge_vs_human']['agreement']}",
                raw=raw_ref(runs.parent, labels.parent / "returned"),
            ))
    return rows


K_ARMS = {
    "fill": {"none": "不带记忆", "raw": "按上下文检索原文", "table_stats": "统计候选梗表", "table_model": "模型提取梗表"},
    "choose": {"none": "不带记忆", "raw_by_word": "按词取 5 条例句", "table": "查词条"},
    "explain": {"none": "不带记忆", "table": "查词条"},
}
K_NAMES = {"fill": "K 梗：自由填词", "choose": "K 梗：四选一", "explain": "K 梗：解释含义"}


def k(runs: Path) -> list[dict]:
    path = runs / "real-dev" / "k.json"
    r = _load(path)
    if not r:
        return []
    rows = []
    k_usage = usage_of(runs / "real-dev", "k")
    prefix = {"fill": "梗填词", "choose": "梗四选一", "explain": "梗解释"}
    for test, arms in K_ARMS.items():
        for key, label in arms.items():
            v = r[test][key]
            metrics = {"n": r[test].get("n", r["items"]), "accuracy": v["acc"], "accuracy_ci95": v["ci95"]}
            if "vs_base" in v:
                metrics["delta_vs_none"] = v["vs_base"]["delta"]
                metrics["delta_ci95"] = v["vs_base"]["ci95"]
            rows.append(row(
                K_NAMES[test], label,
                cond(index="梗表" if "table" in key else ("原文" if key != "none" else "-"),
                     chunking="5 条窗口" if key == "raw" else "-", tokenizer="jieba+梗表词", top_k=5, filter="否",
                     feed=label, model_main=GEMINI, judge=GPT if test == "explain" else "精确匹配", seed=r["seed"]),
                metrics, dataset="QQ", split=SPLIT.get(r["group"], r["group"]), when=_when(path),
                tokens={("回答" if role == prefix[test] else role.replace(f"|{prefix[test]}", "")): v
                        for role, v in for_arm(k_usage, key).items()
                        if role in (prefix[test], f"判官|{prefix[test]}")},
                data={"tables": fingerprint(runs / "real-dev" / "k_tables.json")},
                raw=raw_ref(runs, runs / "real-dev" / "raw" / "k" / "items.jsonl"),
                note="建表用前 70% 时间，测试用后 30%",
            ))
    return rows


def abcd(runs: Path, folder: str = "real-dev", name: str = "abcd") -> list[dict]:
    path = runs / folder / f"{name}.json"
    r = _load(path)
    if not r:
        return []
    rows = []
    abcd_usage = usage_of(runs / folder, name)
    title = {"abcd": "R4/I3 检索对象 × 交给模型", "vector": "I4 向量检索（1500 字）", "packing": "E 打包与保底（1500 字）",
             "depth": "K 候选深度（E1，1500 字）",
             "depth_V2": "K 候选深度（E1，1500 字；向量 V2 补测，2026-11-07）",
             "packing_V2": "E 打包与保底（1500 字；向量 V2 补测，2026-11-07）",
             "vector_V2": "I4 向量检索（1500 字；向量 V2 补测，2026-11-07）",
             "embed_qa": "I5 向量配置（问答层，冻结版框架）",
             "embed_qa_B": "I5 向量配置问答层补测（B 去重不合并，D-032；2026-11-07）",
             "color_fix": "C 上色修正 merged-v1（冻结版 V2；与此前实验条件不同）"}[name]
    for arm_name, a in r["arms"].items():
        from bench.run_abcd import arm_conditions

        c = a.get("conditions") or arm_conditions(arm_name)
        original = {"n": sum(x["visible"] for x in a["rows"]), **{k: v for k, v in a.items() if k not in ("rows", "conditions")}}
        rows.append(row(
            f"{title}（{SPLIT.get(r['group'], r['group'])}）", arm_name, c,
            with_three_state(original, a["rows"]),
            dataset="QQ", split=SPLIT.get(r["group"], r["group"]), when=_when(path), data=r.get("data", {}),
            tokens=for_arm(abcd_usage, arm_name),
            raw=raw_ref(runs, arm_file(runs / folder, name, arm_name)),
        ))
    return rows


def backfill(runs: Path) -> list[dict]:
    labels = runs.parent / "labels" / "round1" / "merged.json"
    costs = cost_rows(runs / "real-dev", "DEV-1") + cost_rows(runs / "real-dev2", "DEV-2")
    tables = [abcd(runs, f, n) for f in ("real-dev", "real-dev2") for n in ("abcd", "vector", "packing", "packing_V2", "depth", "depth_V2", "embed_qa", "embed_qa_B", "color_fix")]
    return gmb(runs) + q1(runs) + q2(runs, labels) + k(runs) + sum(tables, []) + costs
