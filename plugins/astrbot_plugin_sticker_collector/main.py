"""AstrBot plugin: collect stickers/images into a local dataset (no sending).

- Listens to every message and saves sticker-like images (raw OneBot image
  segment has sub_type / summary) or GIFs into data/sticker_dataset/inbox.
- Manual add: reply to / quote an image and send ``/sticker add`` (admin).
- Never registers a send tool and never sends messages, so the model cannot
  send stickers while this plugin is installed.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Reply
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .store import (
    dataset_root,
    ensure_layout,
    has_sticker_signal,
    infer_ext,
    save_image,
    MAX_BYTES,
)


def _raw_image_signals(event: AstrMessageEvent) -> list[dict]:
    """Extract per-image raw OneBot data (sub_type/summary survive here)."""
    raw = getattr(event.message_obj, "raw_message", None)
    segments = getattr(raw, "message", None)
    if segments is None and isinstance(raw, dict):
        segments = raw.get("message")
    if not isinstance(segments, list):
        return []
    result = []
    for seg in segments:
        if not isinstance(seg, dict) or seg.get("type") != "image":
            continue
        data = dict(seg.get("data") or {})
        data["_seg_type"] = "image"
        result.append(data)
    return result


@register(
    "astrbot_plugin_sticker_collector",
    "qqbot",
    "只采集表情包到本地数据集（不发送、无 LLM 工具），供后续标注/评估",
    "0.1.0",
)
class StickerCollectorPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        base = Path(get_astrbot_data_path())
        self.root = dataset_root(base)
        ensure_layout(self.root)
        self._lock = asyncio.Lock()
        logger.info("[sticker-collector] dataset dir: %s", self.root)

    async def _save_components(
        self,
        event: AstrMessageEvent,
        components: list,
        manual: bool,
        signals_list: list[dict],
    ) -> int:
        images = [c for c in components if isinstance(c, Image)]
        saved = 0
        for idx, comp in enumerate(images):
            signals = dict(signals_list[idx]) if idx < len(signals_list) else {}
            if not manual and not signals:
                # fall back: still collect GIFs; other unknown images are ignored
                if not str(getattr(comp, "file", "") or "").lower().endswith(".gif"):
                    continue
            try:
                path = await comp.convert_to_file_path()
            except Exception as exc:  # noqa: BLE001
                logger.warning("[sticker-collector] download failed: %s", exc)
                continue
            try:
                size = os.path.getsize(path)
                if size > MAX_BYTES:
                    logger.info("[sticker-collector] skip large image (%s bytes)", size)
                    continue
                data = Path(path).read_bytes()
            except OSError as exc:
                logger.warning("[sticker-collector] read failed: %s", exc)
                continue
            if not signals:
                signals = {"file": Path(path).name, "mime": ""}
            signals.setdefault("file", Path(path).name)
            signals["mime"] = signals.get("mime") or "image/" + infer_ext(
                signals.get("file", ""), ""
            ).lstrip(".")
            source = "manual" if manual else (
                "group" if "Group" in str(event.get_message_type()) else "private"
            )
            try:
                async with self._lock:
                    image_id, is_new = save_image(
                        self.root,
                        data,
                        source=source,
                        signals=signals,
                        umo=event.unified_msg_origin,
                        sender_id=event.get_sender_id(),
                        manual=manual,
                    )
                if is_new:
                    saved += 1
                    logger.info("[sticker-collector] saved %s", image_id[:12])
            except Exception as exc:  # noqa: BLE001
                logger.warning("[sticker-collector] save failed: %s", exc)
        return saved

    @filter.event_message_type(filter.EventMessageType.ALL, priority=-100)
    async def collect(self, event: AstrMessageEvent) -> None:
        if event.get_sender_id() == event.get_self_id():
            return
        components = event.get_messages()
        if not any(isinstance(c, Image) for c in components):
            return
        signals = _raw_image_signals(event)
        # Only collect images that look like stickers in auto mode.
        candidates = [s for s in signals if has_sticker_signal(s)]
        if not candidates and not any(
            str(getattr(c, "file", "") or "").lower().endswith(".gif")
            for c in components
            if isinstance(c, Image)
        ):
            return
        await self._save_components(event, components, manual=False, signals_list=signals)

    @filter.command("sticker")
    async def sticker_command(self, event: AstrMessageEvent) -> None:
        if not event.is_admin():
            return
        parts = (event.message_str or "").split()
        action = parts[1].lower() if len(parts) > 1 else "status"
        if action == "add":
            components = list(event.get_messages())
            for comp in components:
                if isinstance(comp, Reply) and getattr(comp, "chain", None):
                    components.extend(comp.chain)
            signals = _raw_image_signals(event)
            saved = await self._save_components(
                event, components, manual=True, signals_list=signals
            )
            yield event.plain_result(f"已加入数据集 {saved} 张")
            return
        # status
        labels = self.root / "labels.jsonl"
        inbox = len(list((self.root / "inbox").glob("*")))
        images = len(list((self.root / "images").glob("*")))
        total = sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
        text = (
            f"表情包数据集：inbox {inbox} 张 / 已标注 {images} 张 / "
            f"labels 行数 {sum(1 for _ in labels.open(encoding='utf-8')) if labels.exists() else 0} / "
            f"占用 {total / 1024 / 1024:.1f} MB\n"
            f"路径：{self.root}"
        )
        yield event.plain_result(text)
