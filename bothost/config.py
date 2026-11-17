"""Settings: a JSON file kept outside the repository, secrets from the environment."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    data_dir: Path
    bot_names: list[str]                      # the first one is how the bot is shown in transcripts
    groups: dict[str, str]                    # OneBot group_id -> short alias (letters, digits, -); others are ignored
    model: str
    llm_base_url: str
    llm_images: bool = False                  # the model reads pictures: group images and stickers are given to it as images
    max_images_per_turn: int = 6
    max_image_bytes: int = 4_000_000
    stickers: bool = False                    # stickers are seen by a call of their own, never by the group's session (bothost/stickers.py)
    sticker_model: str = ""                   # its route; empty: the same as the group's model
    sticker_base_url: str = ""
    lookup_model: str = ""                    # the web look-up helper's own route; empty: the same as the group's model
    lookup_base_url: str = ""
    listen_host: str = "127.0.0.1"
    listen_port: int = 6199
    mcp_url: str = ""                         # how the harness reaches this process; default: loopback
    dsh_cmd: list[str] = field(default_factory=lambda: ["dsh"])
    dsh_patches: list[str] = field(default_factory=lambda: [str(REPO / "deploy" / "dsh" / "bot.patch.yml")])
    db_file: str = ""                         # the message store; default: memory.db in data_dir
    history_exclude: list[str] = field(default_factory=list)   # group aliases that recall never returns
    persona_file: str = ""                    # who the bot is and how it talks; kept outside the repository
    snapshot_file: str = ""                   # people and slang the bot always knows; appended after the persona
    debounce_s: float = 2.0                   # wait this long after a trigger for follow-up lines
    turn_timeout_s: float = 300.0
    send_timeout_s: float = 10.0
    lookup_timeout_s: float = 150.0           # one web look-up, done outside the group's session; the tool bridge allows 180 s
    browser_executable: str = ""              # for pages behind a bot check; empty: the system's Chrome
    xvfb_command: str = "Xvfb"
    video_model: str = ""                     # with it, videos are watched by this Gemini model; the key comes from QQBOT_VIDEO_API_KEY
    video_base_url: str = ""                  # a Gemini-native endpoint; empty: the local proxy
    ffmpeg: str = "ffmpeg"
    ytdlp: str = "yt-dlp"
    recap_lines: int = 40                     # raw lines replayed when a session starts
    # One session per group, kept short by compaction. This suits a provider whose prompt cache lasts for days (DeepSeek).
    # Where the cache is short-lived, a new session per day reads less: set daily_session.
    daily_session: bool = False
    compact_at_tokens: int = 110000           # context size at which the oldest part is replaced by the bot's own note
    compact_keep_tokens: int = 5000           # newest part left as written, in the harness's estimate (about 20,000 real tokens of Chinese)
    pending_cap: int = 200
    max_sends_per_turn: int = 3
    max_parallel_turns: int = 4               # groups run side by side; this caps simultaneous model use
    idle_stop_s: float = 1800.0               # a group's harness process is stopped after this long without a turn
    # Session handoff (bothost/handoff.py): a video, or a page that needs the browser, goes on in a copy of the session
    # while a new copy keeps talking in the group. Off: the slow call holds the group's turn, as before.
    handoff: bool = False
    shadow: bool = False                      # shadow test: every message is a chance to talk, nothing is sent (shadow.jsonl)
    shadow_forward_to: str = ""               # shadow test: also show each line privately to this QQ account, with the lines it answers
    shadow_context_lines: int = 4
    handoff_max_tasks: int = 2                # background tasks per group; more run the old way
    handoff_max_total: int = 4                # over all groups
    # With handoff no turn has a time limit (turn_timeout_s and the tool limits apply only without it). A session is
    # cancelled only when it stands still: no event for this long while none of its tool calls is out.
    stall_s: float = 600.0
    handoff_tool_timeout_s: float = 3600.0    # the harness's limit on one tool call; a look-up's own budget is a little under it
    max_message_chars: int = 1500
    onebot_token: str = ""
    llm_api_key: str = ""
    lookup_api_key: str = ""
    sticker_api_key: str = ""
    search_api_key: str = ""                  # web look-up is offered only when this is set
    video_api_key: str = ""

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.db_file = self.db_file or str(self.data_dir / "memory.db")
        self.mcp_url = self.mcp_url or f"http://127.0.0.1:{self.listen_port}/mcp"

def load(path: str | os.PathLike[str]) -> Config:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    raw["groups"] = {str(k): v for k, v in raw["groups"].items()}
    cfg = Config(**raw)
    cfg.onebot_token = os.environ.get("QQBOT_ONEBOT_TOKEN", "")
    cfg.llm_api_key = os.environ.get("QQBOT_LLM_API_KEY", "")
    cfg.lookup_api_key = os.environ.get("QQBOT_LOOKUP_API_KEY", "") or cfg.llm_api_key
    cfg.sticker_api_key = os.environ.get("QQBOT_STICKER_API_KEY", "") or cfg.llm_api_key
    cfg.search_api_key = os.environ.get("QQBOT_SEARCH_API_KEY", "")
    cfg.video_api_key = os.environ.get("QQBOT_VIDEO_API_KEY", "")
    cfg.browser_executable = os.environ.get("BROWSER_EXECUTABLE", cfg.browser_executable)
    cfg.xvfb_command = os.environ.get("XVFB_COMMAND", cfg.xvfb_command)
    if not cfg.onebot_token:
        raise SystemExit("QQBOT_ONEBOT_TOKEN is not set")
    return cfg
