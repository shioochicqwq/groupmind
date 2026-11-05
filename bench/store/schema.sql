-- Memory store (D-030). Raw messages are append-only; everything else is a versioned
-- derivative that points back to messages. Identifiers from the research files are kept
-- in id_map, so every earlier experiment can be traced to the new rows.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY,
  platform TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE            -- pseudonym used by the research files, never the real group id
);

CREATE TABLE IF NOT EXISTS person (
  id INTEGER PRIMARY KEY,
  platform TEXT NOT NULL,
  platform_uid TEXT NOT NULL,
  UNIQUE (platform, platform_uid)
);

CREATE TABLE IF NOT EXISTS person_name (
  person_id INTEGER NOT NULL REFERENCES person(id),
  chat_id INTEGER NOT NULL REFERENCES chat(id),
  name TEXT NOT NULL,
  first_seen REAL NOT NULL,
  last_seen REAL NOT NULL,
  first_message_id INTEGER REFERENCES message(id),
  PRIMARY KEY (person_id, chat_id, name)
);

CREATE TABLE IF NOT EXISTS message (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,                -- e.g. qq:<chat code>
  source_msg_id TEXT NOT NULL,
  chat_id INTEGER NOT NULL REFERENCES chat(id),
  sender_id INTEGER NOT NULL REFERENCES person(id),
  ts REAL NOT NULL,
  order_key INTEGER NOT NULL,
  text TEXT NOT NULL,
  reply_to TEXT,
  media TEXT NOT NULL DEFAULT '',
  nickname_at_time TEXT NOT NULL DEFAULT '',
  UNIQUE (source, source_msg_id)
);
CREATE INDEX IF NOT EXISTS message_chat_order ON message(chat_id, order_key);

CREATE TABLE IF NOT EXISTS color_run (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL REFERENCES chat(id),
  model TEXT NOT NULL,
  source_file TEXT NOT NULL,
  source_sha256 TEXT NOT NULL,
  batch_size INTEGER,
  overlap INTEGER,
  note TEXT NOT NULL DEFAULT '',
  UNIQUE (chat_id, source_sha256)
);

CREATE TABLE IF NOT EXISTS color (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES color_run(id),
  seq INTEGER NOT NULL,                -- line order in the source file
  layer INTEGER NOT NULL DEFAULT 1,
  kind TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  labels TEXT NOT NULL DEFAULT '[]',
  UNIQUE (run_id, seq)
);

CREATE TABLE IF NOT EXISTS color_link (
  color_id INTEGER NOT NULL REFERENCES color(id),
  message_id INTEGER NOT NULL REFERENCES message(id),
  pos INTEGER NOT NULL,                -- order inside the color as stored in the source file
  PRIMARY KEY (color_id, message_id)
);

CREATE TABLE IF NOT EXISTS term (
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL REFERENCES chat(id),
  surface TEXT NOT NULL,
  UNIQUE (chat_id, surface)
);

CREATE TABLE IF NOT EXISTS term_sense (
  id INTEGER PRIMARY KEY,
  term_id INTEGER NOT NULL REFERENCES term(id),
  source_table TEXT NOT NULL,          -- which research table it came from (model / stats)
  meaning TEXT NOT NULL,
  usage TEXT NOT NULL DEFAULT '',
  confidence TEXT NOT NULL DEFAULT '',
  learned_before REAL,
  status TEXT NOT NULL DEFAULT 'candidate',
  UNIQUE (term_id, source_table)
);

CREATE TABLE IF NOT EXISTS evidence (
  object_type TEXT NOT NULL,
  object_id INTEGER NOT NULL,
  message_id INTEGER NOT NULL REFERENCES message(id),
  role TEXT NOT NULL DEFAULT 'support',
  PRIMARY KEY (object_type, object_id, message_id, role)
);

-- Old identifier -> new row, one line per object. The same rows are also written to a
-- separate JSONL file (see bench.store.importer) so the mapping survives without the database.
CREATE TABLE IF NOT EXISTS id_map (
  kind TEXT NOT NULL,                  -- chat | person | message | color_run | color | term | term_sense
  chat_code TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT '',      -- e.g. the colour file for colours, the table name for term senses
  old_id TEXT NOT NULL,
  new_id INTEGER NOT NULL,
  extra TEXT NOT NULL DEFAULT '',      -- e.g. the research alias P### for persons
  PRIMARY KEY (kind, chat_code, scope, old_id)
);

CREATE TABLE IF NOT EXISTS migration (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL,
  code_version TEXT NOT NULL,
  inputs TEXT NOT NULL,                -- JSON: file -> sha256
  verified TEXT NOT NULL DEFAULT ''    -- JSON summary of the equivalence check
);
