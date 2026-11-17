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
    for bad in ("/etc/passwd", "file:///etc/passwd", "http://127.0.0.1:8317/x", "http://user:pw@example.com/v"):
        with pytest.raises(video.VideoError):
            video.public_url(bad)


def test_a_link_straight_to_a_video_file_is_downloaded_as_it_is(tmp_path):
    import http.server, threading
    body = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 2000

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            data = body[:16] if self.headers.get("Range") else body
            self.send_response(206 if self.headers.get("Range") else 200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        got = video._direct_file(f"http://127.0.0.1:{srv.server_port}/v", tmp_path)
        assert got is not None and got.read_bytes() == body
        (tmp_path / "x").mkdir()
        body = b"<html>not a video</html>"
        assert video._direct_file(f"http://127.0.0.1:{srv.server_port}/v", tmp_path / "x") is None
    finally:
        srv.shutdown()
