# 研究数据迁入 SQLite：ID 对照与等价校验

> D-030 的配套说明。研究阶段的实验仍然读 JSONL 文件；这份迁移让同一批数据同时存在于 SQLite 中，并且每个旧 ID 都能对应到新行，所以之前的实验结论不受影响。

## 文件

真实数据都在仓库外：

| 文件 | 内容 |
|---|---|
| `qqbot-data/store/memory.db` | SQLite 库，表结构见 `bench/store/schema.sql` |
| `qqbot-data/store/id_map.jsonl` | **ID 对照表**，每个对象一行 `{kind, chat, scope, old, new, extra}`。库里的 `id_map` 表内容相同；单独存一份文件，是为了即使没有库，对照关系也能保留 |

## 对照表的内容

| kind | old（研究文件里的 ID） | new（库里的行） | scope / extra |
|---|---|---|---|
| chat | 群代号（如 4fe395） | `chat.id` | — |
| person | 发送者的平台 ID | `person.id` | extra 为研究文件里的化名 `P###`（化名每个群一套） |
| message | 平台消息 ID | `message.id` | — |
| color_run | 上色文件名 | `color_run.id` | extra 为文件的 SHA-256 |
| color | 颜色 ID（如 `b0c0`，依赖切批方式） | `color.id` | scope 为上色文件名 |
| term | 梗词本身 | `term.id` | — |
| term_sense | `<表名>:<词>` | `term_sense.id` | scope 为来源表（model / stats） |

问题 ID（`q2:…`、`q2b:…`）属于评测，不迁入库。问题里的证据消息 ID 通过 `message` 这一类即可对应到新行。

## 命令

```bash
python -m bench.store.importer import --db <data>/store/memory.db --map <data>/store/id_map.jsonl \
  --groups 4fe395=<runs>/real-dev ed14b7=<runs>/real-dev2
python -m bench.store.importer verify --db <data>/store/memory.db \
  --groups 4fe395=<runs>/real-dev ed14b7=<runs>/real-dev2 --labels <labels>/round1/merged.json
```

只导入 DEV 群；FROZEN 群在研究阶段不导入。

## 等价校验（2026-11-05 首次迁移）

| 检查 | DEV-1 | DEV-2 |
|---|---|---|
| 从库里还原的消息与原文件逐条相同（全部字段与顺序） | 15,841 条，相同 | 46,200 条，相同 |
| 从库里还原的颜色（通过对照表恢复旧 ID）与上色文件相同 | 828 个，相同 | 2,451 个，相同 |
| 颜色里指向不存在消息的链接 | 0 | 0 |
| 用库里的数据重建摘要索引，BM25 前 30 名与原来相同的题 | 440 / 440 | 436 / 436 |
| 用库里的数据重建原文块索引，同上 | 440 / 440 | 436 / 436 |

另外导入了人物 104 人和 81 人、称呼历史 144 条和 125 条，以及 DEV-1 的梗表（两张表共 66 条含义）。对照表共 65,641 行。校验结果写在库的 `migration.verified` 字段里。

## 规则

- 研究文件仍然是实验的源头。库里的数据只有在 `verify` 通过之后，才可以用于实验。
- 研究文件以后如果有变化，比如重新上色，就再导入一次。新的上色记为新的 `color_run`，旧的不覆盖；对照表追加新行。
- 梗表原本没有记录证据消息，所以 `evidence` 表暂时是空的。以后建表时由代码补上证据。
