"""Offline labeling pages: one self-contained HTML file per pack (kit.css, kit.js, a page script, data)."""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent


def build(page: str, title: str, data: dict, out: Path) -> Path:
    """page is a script under pages/ (without .js); it reads window.DATA and uses window.LabelKit."""
    css = (HERE / "kit.css").read_text(encoding="utf-8")
    kit = (HERE / "kit.js").read_text(encoding="utf-8")
    script = (HERE / "pages" / f"{page}.js").read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = (f'<!doctype html>\n<html lang="zh"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title>'
            f"<style>{css}</style></head><body><div id=\"app\"></div>"
            f"<script>window.DATA = {blob};</script><script>{kit}</script><script>{script}</script></body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
