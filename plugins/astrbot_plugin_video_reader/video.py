"""Fetch a video, cut it into model-sized pieces, ask a Gemini model about each, merge.

Why: the Gemini route we use (gateway, Gemini-native generateContent, D-036) has no Files API,
so video goes inline as base64 and one request holds at most ~20 MiB. A long video has to be
shrunk and split, every piece asked the same question with its place in the source, and the
answers merged back with source timestamps. Nothing here depends on AstrBot.

  acquire(url or path)   yt-dlp download (any site yt-dlp supports) or a local file
  prepare(path)          one transcode to a model-ready profile (low resolution, few fps,
                         mono low-bitrate audio), then split on forced keyframes so that every
                         piece is under the inline limit; returns Segment(path, start, end)
  ask_segments(...)      one generateContent call per piece, prompt carries the source window
  merge(...)             one text call that answers from the per-piece notes
  answer(...)            the whole chain
  watch(...)             what a tool shows: the answer, and for a Bilibili link what the page says in text

Model sees at about 1 frame per second anyway, so 2 fps at 360p loses little for it while a
10-minute piece shrinks to a few MiB.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import ipaddress
import json
import math
import os
import re
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlsplit

try:
    from . import bilibili
except ImportError:   # loaded on its own, by path
    import bilibili

INLINE_LIMIT = 19 * 1024 * 1024  # leave headroom under the ~20 MiB request cap (base64 grows 4/3)
INLINE_RAW_LIMIT = INLINE_LIMIT * 3 // 4
MAX_SEGMENT_SECONDS = 600
MIN_SEGMENT_SECONDS = 20
MAX_SOURCE_SECONDS = 3 * 3600
PROFILE = {"height": 360, "fps": 2, "crf": 32, "audio_kbps": 32}

SEGMENT_PROMPT = """你在看一段视频的一个片段：它对应原视频的 {start} 到 {end}（共 {total}）。
问题：{question}

只根据这个片段里看到和听到的内容记录与问题有关的信息：
1. 带时间的直接观察，时间一律写成**原视频时间**（片段开头 = {start}）；
2. 画面里的文字、字幕、说话内容（原话尽量照录）；
3. 不确定或看不清的地方直说。
和问题无关的片段，只用一两句话概括这段在讲什么。"""

MERGE_PROMPT = """下面是同一个视频按时间切成 {n} 段后，各段分别记下的笔记（时间都是原视频时间）。
视频信息：{meta}
问题：{question}

只根据这些笔记回答问题：先给结论，再给关键依据和时间点。笔记之间矛盾或信息不够时直说，不要补充笔记里没有的内容。

{notes}"""


class VideoError(RuntimeError):
    pass


@dataclass
class Segment:
    path: Path
    start: float
    end: float

    @property
    def size(self) -> int:
        return self.path.stat().st_size


@dataclass
class Config:
    base_url: str = "http://127.0.0.1:8317"
    api_key: str = ""
    model: str = "gemini-3.8-flash-high"
    ffmpeg: str = "ffmpeg"
    ytdlp: str = "yt-dlp"
    cookies_file: str = ""
    proxy: str = ""
    workers: int = 3
    timeout: int = 300
    profile: dict = field(default_factory=lambda: dict(PROFILE))


def public_url(url: str) -> str:
    """The model may only name public http(s) pages: no local files, no hosts on this machine or its network."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise VideoError("只接受公开的 http/https 视频链接")
    for info in socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP):
        addr = ipaddress.ip_address(info[4][0])
        if addr.version == 6 and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
            raise VideoError("禁止访问本机/内网地址")
    return url.strip()


def fmt_ts(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _run(cmd: list[str], timeout: int = 1800) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        tail = (r.stderr or r.stdout or "").strip().splitlines()[-3:]
        raise VideoError(f"{Path(cmd[0]).name} failed: {' | '.join(tail)[:300]}")
    return r


_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def duration(cfg: Config, path: Path) -> float:
    """ffmpeg -i prints the container duration on stderr (no ffprobe needed)."""
    r = subprocess.run([cfg.ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60)
    m = _DURATION.search(r.stderr)
    if not m:
        raise VideoError("cannot read video duration (not a video file?)")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def acquire(cfg: Config, source: str, workdir: Path) -> tuple[Path, dict]:
    """A local file is used as is; a URL goes through yt-dlp at <=720p. Returns (path, metadata)."""
    p = Path(source)
    if p.is_file():
        return p, {"title": p.name}
    if not re.match(r"^https?://", source):
        raise VideoError("not a URL or an existing file")
    direct = _direct_file(source, workdir, cfg.proxy)
    if direct is not None:
        return direct, {"title": "群里发的视频文件"}
    args = [cfg.ytdlp, "--no-playlist", "--no-warnings", "--restrict-filenames", "--ffmpeg-location", cfg.ffmpeg,
            "-f", "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b", "--merge-output-format", "mp4",
            "--print-json", "-o", str(workdir / "source.%(ext)s")]
    if cfg.cookies_file:
        args += ["--cookies", cfg.cookies_file]
    if cfg.proxy:
        args += ["--proxy", cfg.proxy]
    r = _run(args + [source], timeout=1800)
    meta = {}
    for line in r.stdout.splitlines():
        if line.startswith("{"):
            try:
                j = json.loads(line)
                meta = {k: j.get(k) for k in ("title", "uploader", "duration", "upload_date", "webpage_url", "description")}
                meta["description"] = (meta.get("description") or "")[:500]
            except json.JSONDecodeError:
                pass
    files = sorted(x for x in workdir.glob("source.*") if x.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov", ".flv"))
    if not files:
        raise VideoError("yt-dlp finished without a video file")
    return files[0], meta


VIDEO_MAGIC = ((4, b"ftyp"), (0, b"\x1a\x45\xdf\xa3"), (0, b"FLV"))   # MP4/MOV, Matroska/WebM, FLV
DIRECT_LIMIT = 1024 * 1024 * 1024


def _direct_file(url: str, workdir: Path, proxy: str = "") -> Path | None:
    """A link straight to a video file (e.g. one sent in a QQ group: its server says application/octet-stream, which
    yt-dlp does not take for a video) is downloaded as it is. None when the link is not a video file."""
    import urllib.request
    opener = urllib.request.build_opener(*([urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []))
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        with opener.open(urllib.request.Request(url, headers={**headers, "Range": "bytes=0-15"}), timeout=15) as r:
            head = r.read(16)
    except (OSError, ValueError):
        return None
    if not any(head[at:at + len(magic)] == magic for at, magic in VIDEO_MAGIC):
        return None
    out = workdir / "source.mp4"
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=60) as r, out.open("wb") as f:
            got = 0
            while chunk := r.read(1 << 20):
                got += len(chunk)
                if got > DIRECT_LIMIT:
                    raise VideoError("视频文件太大（超过 1 GB）")
                f.write(chunk)
    except OSError as e:
        raise VideoError(f"视频文件下载失败：{type(e).__name__}") from e
    return out


def segment_seconds(total: float, bytes_per_sec: float, limit: int | None = None) -> int:
    """Longest piece that stays under the inline limit, within [MIN, MAX]; pieces of equal length."""
    limit = INLINE_RAW_LIMIT if limit is None else limit
    fit = int(limit * 0.92 / max(bytes_per_sec, 1.0))
    length = max(MIN_SEGMENT_SECONDS, min(MAX_SEGMENT_SECONDS, fit))
    if total <= length:
        return int(math.ceil(total))
    n = math.ceil(total / length)
    return int(math.ceil(total / n))


def _transcode(cfg: Config, src: Path, dst: Path, start: float | None, end: float | None, prof: dict,
               keyframe_every: int | None) -> None:
    cmd = [cfg.ffmpeg, "-hide_banner", "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if end is not None:
        cmd += ["-t", f"{end - (start or 0):.3f}"]
    vf = f"scale=-2:'min({prof['height']},ih)',fps={prof['fps']}"
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(prof["crf"]), "-pix_fmt", "yuv420p"]
    if keyframe_every:
        cmd += ["-force_key_frames", f"expr:gte(t,n_forced*{keyframe_every})"]
    if prof.get("audio_kbps"):
        cmd += ["-c:a", "aac", "-ac", "1", "-b:a", f"{prof['audio_kbps']}k"]
    else:
        cmd += ["-an"]
    _run(cmd + ["-movflags", "+faststart", str(dst)], timeout=3600)


def prepare(cfg: Config, src: Path, workdir: Path, start: float | None = None, end: float | None = None) -> tuple[list[Segment], float]:
    """Transcode once, split into pieces under the inline limit. Returns (segments, source duration)."""
    total = duration(cfg, src)
    if total > MAX_SOURCE_SECONDS and start is None:
        raise VideoError(f"video is {fmt_ts(total)} long; give a time window (start/end) for videos over {fmt_ts(MAX_SOURCE_SECONDS)}")
    s0 = max(0.0, start or 0.0)
    e0 = min(total, end) if end else total
    if e0 <= s0:
        raise VideoError("empty time window")
    prof = dict(cfg.profile)
    ss, to = (s0 if s0 > 0 else None), (e0 if e0 < total else None)
    span = e0 - s0
    for _attempt in range(3):
        # Keyframes every MIN_SEGMENT_SECONDS, so any multiple of it can be cut by stream copy.
        small = workdir / "model.mp4"
        _transcode(cfg, src, small, ss, to, prof, MIN_SEGMENT_SECONDS)
        if small.stat().st_size <= INLINE_RAW_LIMIT:
            return [Segment(small, s0, e0)], total
        bps = small.stat().st_size / max(span, 1.0)
        seg = segment_seconds(span, bps) // MIN_SEGMENT_SECONDS * MIN_SEGMENT_SECONDS
        if seg < MIN_SEGMENT_SECONDS:
            prof = {**prof, "height": max(144, prof["height"] * 2 // 3), "crf": prof["crf"] + 4, "fps": 1}
            continue
        for old in workdir.glob("part_*.mp4"):
            old.unlink()
        _run([cfg.ffmpeg, "-hide_banner", "-v", "error", "-y", "-i", str(small), "-c", "copy", "-map", "0",
              "-f", "segment", "-segment_time", str(seg), "-reset_timestamps", "1", str(workdir / "part_%03d.mp4")])
        segs, t = [], s0
        for p in sorted(workdir.glob("part_*.mp4")):
            d = duration(cfg, p)
            segs.append(Segment(p, t, min(e0, t + d)))
            t += d
        if all(x.size <= INLINE_RAW_LIMIT for x in segs):
            return segs, total
        prof = {**prof, "height": max(144, prof["height"] * 2 // 3), "crf": prof["crf"] + 4}
    raise VideoError("could not bring the pieces under the inline size limit")


def _generate(cfg: Config, parts: list[dict]) -> tuple[str, dict]:
    url = f"{cfg.base_url.rstrip('/')}/v1beta/models/{cfg.model}:generateContent"
    body = json.dumps({"contents": [{"role": "user", "parts": parts}]}).encode()
    req = urllib.request.Request(url, body, {"Content-Type": "application/json", "Authorization": f"Bearer {cfg.api_key}"})
    try:
        with urllib.request.urlopen(req, timeout=cfg.timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:   # say which side failed: the video was fetched, the model did not take it
        raise VideoError(f"video model answered HTTP {e.code}: {e.read()[:200].decode('utf-8', 'replace')}") from None
    except OSError as e:
        raise VideoError(f"video model not reachable: {e}") from None
    cand = (data.get("candidates") or [{}])[0]
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []) if not p.get("thought"))
    if not text.strip():
        raise VideoError(f"empty model answer ({cand.get('finishReason', 'no candidate')})")
    return text.strip(), data.get("usageMetadata", {})


def ask_segment(cfg: Config, seg: Segment, total: float, question: str) -> tuple[str, dict]:
    prompt = SEGMENT_PROMPT.format(start=fmt_ts(seg.start), end=fmt_ts(seg.end), total=fmt_ts(total), question=question)
    data = base64.b64encode(seg.path.read_bytes()).decode()
    return _generate(cfg, [{"inlineData": {"mimeType": "video/mp4", "data": data}}, {"text": prompt}])


def answer(cfg: Config, source: str, question: str, start: float | None = None, end: float | None = None,
           keep: Path | None = None, cookies: Callable[[str], str] | None = None) -> dict:
    """The whole chain. Returns {answer, segments:[{start,end,bytes,notes}], meta, usage}.

    cookies(folder): called when the download is refused; writes a cookies.txt for this site into the folder and
    returns its path (empty: none to give). The download is then tried once more with it. Some sites answer a bare
    downloader with an error and a browser's visitor cookies, or a login, are what they want to see."""
    workdir = Path(tempfile.mkdtemp(prefix="vr-", dir=keep))
    try:
        try:
            src, meta = acquire(cfg, source, workdir)
        except VideoError:
            jar = cookies(str(workdir)) if cookies and not cfg.cookies_file else ""
            if not jar:
                raise
            src, meta = acquire(replace(cfg, cookies_file=jar), source, workdir)
        segs, total = prepare(cfg, src, workdir, start, end)
        meta["duration"] = round(total, 1)
        usage = {"prompt": 0, "completion": 0, "calls": 0}

        def one(s: Segment):
            return ask_segment(cfg, s, total, question)

        with cf.ThreadPoolExecutor(max(1, cfg.workers)) as ex:
            results = list(ex.map(one, segs))
        rows = []
        for s, (text, u) in zip(segs, results):
            usage["prompt"] += u.get("promptTokenCount", 0)
            usage["completion"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
            usage["calls"] += 1
            rows.append({"start": round(s.start, 1), "end": round(s.end, 1), "bytes": s.size, "notes": text})
        if len(rows) == 1:
            final = rows[0]["notes"]
        else:
            notes = "\n\n".join(f"【{fmt_ts(r['start'])}–{fmt_ts(r['end'])}】\n{r['notes']}" for r in rows)
            m = {k: v for k, v in meta.items() if k in ("title", "uploader", "duration") and v}
            final, u = _generate(cfg, [{"text": MERGE_PROMPT.format(n=len(rows), meta=json.dumps(m, ensure_ascii=False),
                                                                     question=question, notes=notes)}])
            usage["prompt"] += u.get("promptTokenCount", 0)
            usage["completion"] += u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)
            usage["calls"] += 1
        return {"answer": final, "segments": rows, "meta": meta, "usage": usage}
    finally:
        if keep is None:
            shutil.rmtree(workdir, ignore_errors=True)


def headline(r: dict) -> str:
    """What was watched, for the top of a tool's reply."""
    meta = r["meta"]
    head = f"视频：{meta.get('title') or '(无标题)'}；时长 {fmt_ts(meta.get('duration') or 0)}；分 {len(r['segments'])} 段看"
    return head + (f"；UP/作者：{meta['uploader']}" if meta.get("uploader") else "")


def watch(cfg: Config, url: str, question: str, start: float | None = None, end: float | None = None,
          cookies: Callable[[str], str] | None = None) -> tuple[str, dict]:
    """The reply of a tool and the model use. A Bilibili link also brings the page's text (description, tags, comments);
    when the video itself cannot be fetched, that text is returned alone and says so."""
    page = bilibili.page_text(url) if bilibili.is_ours(url) else ""
    try:
        r = answer(cfg, url, question, start, end, cookies=cookies)
    except VideoError as e:
        if not page:
            raise
        return f"画面没看成（{e}）。下面只有视频页面上的文字：画面和声音里讲了什么不知道，不要编。\n\n{page}", {}
    return f"{headline(r)}\n\n{r['answer']}" + (f"\n\n【视频页面上的文字】\n{page}" if page else ""), r["usage"]


def config_from_env() -> Config:
    """For scripts and tests: VIDEO_READER_* variables, ffmpeg/yt-dlp from PATH."""
    return Config(base_url=os.environ.get("VIDEO_READER_BASE_URL", Config.base_url),
                  api_key=os.environ.get("VIDEO_READER_API_KEY", ""),
                  model=os.environ.get("VIDEO_READER_MODEL", Config.model),
                  ffmpeg=os.environ.get("VIDEO_READER_FFMPEG", "ffmpeg"),
                  ytdlp=os.environ.get("VIDEO_READER_YTDLP", "yt-dlp"),
                  cookies_file=os.environ.get("VIDEO_READER_COOKIES", ""),
                  proxy=os.environ.get("VIDEO_READER_PROXY", ""))
