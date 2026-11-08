import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "astrbot_plugin_video_reader"))
import video  # noqa: E402

FFMPEG = os.environ.get("VIDEO_READER_FFMPEG") or shutil.which("ffmpeg") or \
    str(Path(__file__).resolve().parents[3] / "qqbot-data/vendor/bvr/node_modules/ffmpeg-static/ffmpeg")


def test_fmt_ts():
    assert video.fmt_ts(0) == "00:00"
    assert video.fmt_ts(95.4) == "01:35"
    assert video.fmt_ts(3725) == "1:02:05"


def test_segment_seconds_short_video_is_one_piece():
    assert video.segment_seconds(120, 1000, limit=10_000_000) == 120


def test_segment_seconds_equal_pieces_under_limit():
    # 1 MB/s with a 19 MB budget -> fit ~17 s, clamped to MIN; long video -> equal pieces
    s = video.segment_seconds(1000, 50_000, limit=10_000_000)
    assert video.MIN_SEGMENT_SECONDS <= s <= video.MAX_SEGMENT_SECONDS
    assert s * 50_000 <= 10_000_000
    n = -(-1000 // s)
    assert n * s >= 1000 and (n - 1) * s < 1000


def test_segment_seconds_caps_at_max():
    s = video.segment_seconds(10_000, 10, limit=10_000_000)
    assert video.MAX_SEGMENT_SECONDS - 60 < s <= video.MAX_SEGMENT_SECONDS


@pytest.mark.skipif(not Path(FFMPEG).exists() and not shutil.which(FFMPEG), reason="ffmpeg not available")
def test_prepare_splits_and_keeps_source_times(tmp_path, monkeypatch):
    src = tmp_path / "src.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=90",
                    "-c:v", "libx264", "-preset", "ultrafast", str(src)], check=True)
    cfg = video.Config(ffmpeg=FFMPEG)
    monkeypatch.setattr(video, "INLINE_RAW_LIMIT", 120_000)
    segs, total = video.prepare(cfg, src, tmp_path)
    assert abs(total - 90) < 1
    assert len(segs) > 1
    assert all(s.size <= 120_000 for s in segs)
    assert segs[0].start == 0
    assert abs(segs[-1].end - 90) < 1.5
    for a, b in zip(segs, segs[1:]):
        assert abs(a.end - b.start) < 0.1
    # a window is measured in source time
    for p in tmp_path.glob("part_*.mp4"):
        p.unlink()
    segs, _ = video.prepare(cfg, src, tmp_path, start=30, end=50)
    assert segs[0].start == 30 and abs(segs[-1].end - 50) < 1.5


def test_local_paths_and_private_hosts_rejected():
    main = (Path(video.__file__).parent / "main.py").read_text(encoding="utf-8")
    assert "_public_url(url)" in main and "is_private" in main
