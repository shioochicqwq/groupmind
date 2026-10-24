# 外部插件清单（版本锁定 / 安装 / 回滚）

> 原则：外部插件安装到 `data/plugins/`（gitignored），但**必须锁定提交并记录在此**；
> 升级前备份 `data/`，升级后跑 healthcheck + 关键回归。

| 插件 | 版本 / 提交 | 许可证 | 用途 | 数据目录 |
|---|---|---|---|---|
| `astrbot_plugin_memory_beyond` | v1.3.7 `0ec75bfb1a36a416121088d19acd7027ac9c0274` | MIT | 记忆本子 + 上下文压缩（D-013） | `data/plugin_data/astrbot_plugin_memory_beyond/` |
| `astrbot_plugin_strip_refs`（本项目） | 0.1.0（本仓库） | — | 剥离 QQ 回复里的 `<ref>` | 无 |

## memory_beyond 安装（固定提交）

```powershell
git clone https://github.com/AlanBacker/astrbot_plugin_memory_beyond data/plugins/astrbot_plugin_memory_beyond
git -C data/plugins/astrbot_plugin_memory_beyond checkout 0ec75bfb1a36a416121088d19acd7027ac9c0274
# 重启 AstrBot；首次启动会生成 data/config/astrbot_plugin_memory_beyond_config.json
```

配置（`data/config/astrbot_plugin_memory_beyond_config.json`，首次生成后改）：

| 配置 | 值 | 说明 |
|---|---|---|
| `enable_memory` | true | 记忆索引 + 4 个记忆工具 |
| `enable_people_memory` | true | 跨会话人物记忆（按 QQ 号锚定） |
| `enable_global_memory` | false | 先关，避免群友污染 bot 全局规则 |
| `recall_max_files` | 3 | 每轮最多召回 3 条，控制 token |
| `max_context_tokens` | 128000 | deepseek 窗口；换 1M 模型时调大 |
| `summary_provider_id` | gemini-3.8-flash | 摘要用便宜快模型 |
| `consolidate_provider_id` | claude-sonnet-4-6 | 手动整理记忆用强模型 |
| `compress_threshold` | 0.7 | 早于内置 0.82 触发 |
| `summary_max_chars` | 1500 | 摘要上限（每轮固定开销） |
| `auto_extract_interval` | 10 | 每 10 轮后台补记 |
| `enable_forgetting` | false | 先不遗忘 |

同时需要改 AstrBot 主配置（`scripts/bootstrap_astrbot_config.py` 已包含）：

- `agent_runner.config.compression.fallback_max_tokens = 1000000000`、`max_turns = -1`（让内置压缩不介入）；
- `provider_settings.identifier = false`（发送者标注交给插件）。

## 升级 / 回滚

```powershell
# 升级（先看 diff + CHANGELOG，记录新提交）
git -C data/plugins/astrbot_plugin_memory_beyond pull
git -C data/plugins/astrbot_plugin_memory_beyond checkout <新提交>
# 回滚
git -C data/plugins/astrbot_plugin_memory_beyond checkout 0ec75bf...
# 然后重启 AstrBot；必要时恢复 data/ 备份
```

## 注意

- 插件会接管压缩与身份标注，**不要同时开启 AstrBot 内置压缩/identifier**，否则双重压缩/重复标注；
- 人物记忆跨群可见（A 群说的可能在 B 群用到），隐私敏感时关掉 `enable_people_memory`；
- 升级/换插件后跑：`scripts/healthcheck.py`、`smoke_llm.py --no-stream`、私聊记忆回归（说事实 → `/reset` → 追问）。
