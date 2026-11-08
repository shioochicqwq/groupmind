"""Build the always-injected memory snapshot (people + slang) for the RP test session.

Sources (all outside the repository):
  labels/k-round1/merged-k-round1-v2.json  people, term verdicts, recall words
  labels/term_refs.v1.json                 71 terms with human-checked references

Output: qqbot-data/store/memory_snapshot.md — a short Markdown block that is
prepended to the system prompt on every request. Only names/aliases/one-line
meanings are written; no account ids, no chat excerpts.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[3] / "qqbot-data"
LABELS = DATA / "labels"
OUT = DATA / "store" / "memory_snapshot.md"
MAX_REF = 80


def load_db_terms() -> dict[str, dict]:
    """Confirmed terms written back from test sessions (term_candidates.py confirm).

    chat code 'general' means the shared layer; any other code is that group's local layer.
    Database entries override the same surface from labelling files, because they were
    confirmed later and by hand.
    """
    import sqlite3

    db = DATA / "store" / "memory.db"
    if not db.exists():
        return {}
    con = sqlite3.connect(db)
    try:
        rows = con.execute(
            "SELECT c.code, t.surface, s.meaning, s.confidence "
            "FROM term t JOIN chat c ON c.id = t.chat_id JOIN term_sense s ON s.term_id = t.id "
            "WHERE s.status = 'confirmed'"
        ).fetchall()
    finally:
        con.close()
    out: dict[str, dict] = {}
    for code, surface, meaning, confidence in rows:
        surface = str(surface).strip()
        if not surface:
            continue
        layer = "general" if code == "general" else "local"
        out[surface] = {"layer": layer, "meaning": str(meaning or "").strip()}
    return out


def load_terms() -> dict[str, dict]:
    refs = json.loads((LABELS / "term_refs.v1.json").read_text(encoding="utf-8"))
    merged: dict[str, dict] = {}
    for row in refs:
        term = str(row.get("term", "")).strip()
        if not term:
            continue
        merged[term] = {"layer": row.get("layer", "general"), "meaning": str(row.get("reference", "")).strip()}
    for key, verdict in json.loads((LABELS / "k-round1" / "merged-k-round1-v2.json").read_text(encoding="utf-8"))["terms"].items():
        term = key.split(":", 1)[-1].strip()
        if not term or verdict.get("correct") == "wrong":
            continue
        fix = str(verdict.get("fix") or "").strip()
        if fix:
            merged.setdefault(term, {"layer": verdict.get("type", "general"), "meaning": fix})["meaning"] = fix
    merged.update(load_db_terms())
    return merged


def main() -> int:
    labels = json.loads((LABELS / "k-round1" / "merged-k-round1-v2.json").read_text(encoding="utf-8"))
    people = labels.get("people", [])
    terms = load_terms()
    recall = labels.get("recall", [])

    lines = ["# 记忆快照（常驻）", ""]
    lines.append("## 人物")
    lines.append("（来自第一轮打标，只覆盖部分群；没有列出的就是不知道，不要编。）")
    for person in people:
        name = str(person.get("name", "")).strip()
        if not name:
            continue
        aliases = [str(a).strip() for a in person.get("aliases", []) if str(a).strip()]
        accounts = len(person.get("accounts", []))
        extra = f"；外号：{'、'.join(aliases)}" if aliases else ""
        account_note = f"；{accounts} 个账号" if accounts > 1 else ""
        lines.append(f"- {name}{extra}{account_note}")
    if not people:
        lines.append("- （暂无）")

    lines.append("")
    lines.append("## 梗与说法")
    general = [(t, v) for t, v in terms.items() if v.get("layer") != "local"]
    local = [(t, v) for t, v in terms.items() if v.get("layer") == "local"]
    lines.append("### 通用层（各群通用）")
    for term, info in general[:80]:
        meaning = info["meaning"][:MAX_REF].replace("\n", " ")
        lines.append(f"- {term}：{meaning}")
    if not general:
        lines.append("- （暂无）")
    lines.append("### 本群层（只在这个群成立）")
    for term, info in local[:40]:
        meaning = info["meaning"][:MAX_REF].replace("\n", " ")
        lines.append(f"- {term}：{meaning}")
    if not local:
        lines.append("- （暂无）")

    if recall:
        lines.append("")
        lines.append("### 凭记忆想到的词（可能还有")
        for row in recall[:20]:
            word = str(row.get("word", "")).strip()
            meaning = str(row.get("meaning", "")).strip()[:MAX_REF]
            if word:
                lines.append(f"- {word}：{meaning}")

    text = "\n".join(lines) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(json.dumps({"out": str(OUT), "people": len(people), "general": len(general), "local": len(local), "recall": len(recall), "chars": len(text)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
