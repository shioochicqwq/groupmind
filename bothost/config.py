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
    lookup_timeout_s: float = 90.0            # one web look-up, done outside the group's session; the tool bridge allows 120 s
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
    max_message_chars: int = 1500
    onebot_token: str = ""
    llm_api_key: str = ""
    search_api_key: str = ""                  # web look-up is offered only when this is set

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
    cfg.search_api_key = os.environ.get("QQBOT_SEARCH_API_KEY", "")
    if not cfg.onebot_token:
        raise SystemExit("QQBOT_ONEBOT_TOKEN is not set")
    return cfg
