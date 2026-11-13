"""Several labeling pages in one file: one tab per pack, one download for all of them.

Each input is a page written by labelkit.build. Its data and page script are taken as they are and
mounted in their own section when the tab is first opened, so progress is kept under the same
keys as in the separate pages. The per-page "完成" block is replaced by one download at the bottom.

    python -m bench.labelkit.combine --out <labels>/all-r1/label-all-r1.html --title 标注合集 "名字=page.html" ...
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
PAGE = re.compile(r"<script>window\.DATA = (.*?);</script><script>.*?</script><script>(.*)</script></body></html>\s*$", re.S)

SHELL = """
(function () {
  var LK = window.LabelKit, el = LK.el, P = window.PARTS, root = document.getElementById('root');
  var S = LK.store('label:' + window.PACK, { who: '', tab: 0 });
  var note = el('div', 'lk-note');
  note.innerHTML = '<p><b>这页含原名的群聊记录，仅限本人查看，请勿外传。</b>共 ' + P.length + ' 部分，点下面的标签切换，顺序随意。全部是选择题，备注可不填。进度自动保存在本机浏览器里，做完（或做到一半）点最下面的「下载全部结果」，把文件发回来。</p>';
  root.appendChild(el('h1', '', document.title)); root.appendChild(note);
  var tabs = el('div', 'lk-opts'); tabs.style.margin = '10px 0'; root.appendChild(tabs);
  var boxes = P.map(function (p, i) {
    var b = el('button', 'lk-opt', (i + 1) + '. ' + p.name); b.type = 'button'; b.onclick = function () { show(i); }; tabs.appendChild(b);
    var box = el('div'); box.style.display = 'none'; root.appendChild(box); return box;
  });
  function show(i) {
    boxes.forEach(function (x, k) { x.style.display = k === i ? '' : 'none'; tabs.children[k].setAttribute('aria-pressed', k === i ? 'true' : 'false'); });
    if (!boxes[i].dataset.on) {
      boxes[i].dataset.on = '1';
      var old = document.getElementById('app'); if (old) old.removeAttribute('id');
      boxes[i].id = 'app'; window.DATA = P[i].data; P[i].mount();
      var kids = [].slice.call(boxes[i].children), cut = -1;
      kids.forEach(function (c, k) { if (c.tagName === 'H2' && c.textContent === '完成') cut = k; });
      if (cut >= 0) kids.slice(cut).forEach(function (c) { c.remove(); });  // one download for all parts instead
    }
    S.state.tab = i; S.save(); window.scrollTo(0, 0);
  }
  var foot = el('div'); root.appendChild(foot);
  foot.appendChild(el('h2', '', '完成'));
  var who = el('input'); who.type = 'text'; who.placeholder = '你的称呼（用于区分文件）'; who.value = S.state.who || '';
  who.oninput = function () { S.state.who = who.value; S.save(); }; foot.appendChild(who);
  var dl = el('button', 'lk-btn', '下载全部结果'); foot.appendChild(dl);
  dl.onclick = function () {
    var parts = {};
    P.forEach(function (p) {
      var st = null; try { st = JSON.parse(localStorage.getItem('label:' + p.data.pack) || 'null'); } catch (e) { /* private mode */ }
      parts[p.data.pack] = { name: p.name, group: p.data.group, state: st };
    });
    LK.download({ pack: window.PACK, who: S.state.who, savedAt: new Date().toISOString(), parts: parts },
      'labels-' + window.PACK + (S.state.who ? '-' + S.state.who : '') + '.json');
  };
  show(Math.min(S.state.tab || 0, P.length - 1));
})();
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("parts", nargs="+", help="name=path of a page written by labelkit.build")
    args = ap.parse_args()
    chunks = []
    for part in args.parts:
        name, path = part.split("=", 1)
        data, script = PAGE.search(Path(path).read_text(encoding="utf-8")).groups()
        chunks.append(f"{{name: {json.dumps(name, ensure_ascii=False)}, data: {data}, mount: function () {{\n{script}\n}}}}")
    css, kit = (HERE / "kit.css").read_text(encoding="utf-8"), (HERE / "kit.js").read_text(encoding="utf-8")
    pack = args.out.stem.removeprefix("label-")
    html = (f'<!doctype html>\n<html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{args.title}</title>'
            f'<style>{css}</style></head><body><div id="root"></div><script>{kit}</script>'
            f'<script>window.PACK = {json.dumps(pack)}; window.PARTS = [{",".join(chunks)}];</script><script>{SHELL}</script></body></html>')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    print(args.out, len(chunks), "parts", len(html) // 1024, "KiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
