"""Does a reader hand over the next link on the known path to the answer? (no model)

For each deep case, the path is a list of hops; a hop is satisfied when some returned link's URL
contains one of its patterns. The page that link points to is read for the next hop.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backends  # noqa: E402

PATHS = {
    "k2": ("https://github.com/7oMB2006/Bilibili-Video-Research", [["/tree/main/src", "/blob/main/src/index.ts"], ["/blob/main/src/index.ts"]]),
    "k3": ("https://docs.python.org/3/", [["library/index.html"], ["library/json.html"]]),
    "k4": ("https://docs.searxng.org/", [["dev/search_api"]]),
    "k5": ("https://docs.crawl4ai.com/", [["core/browser-crawler-config"]]),
}


def run(backend: str) -> dict:
    out = {}
    for cid, (url, hops) in PATHS.items():
        steps, cur = [], url
        for pats in hops:
            d = backends.read(backend, cur)
            if not d["ok"]:
                steps.append({"page": cur, "error": d["error"][:80]})
                break
            hit = next((h for _, h in d["links"] if any(p in h for p in pats)), None)
            steps.append({"page": cur, "links": len(d["links"]), "next": hit})
            if not hit:
                break
            if hit.endswith(pats[-1]) or pats == hops[-1]:
                cur = hit
                if pats == hops[-1]:
                    break
            cur = hit
        out[cid] = {"exposed": all(s.get("next") for s in steps) and len(steps) == len(hops), "steps": steps}
    return out


if __name__ == "__main__":
    res = {b: run(b) for b in sys.argv[1:]}
    print(json.dumps(res, ensure_ascii=False, indent=1))
