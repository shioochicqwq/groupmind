# 群聊陪聊 / 整活调参指南

> 对应配置位于 `data/cmd_config.json`，由 `scripts/bootstrap_astrbot_config.py` 幂等写入。
> 修改后重启 AstrBot 生效。人设由 `config/personas/example.json` + `scripts/apply_persona.py` 管理。

## 1. 当前策略（2026-10-24，首次可用版本）

| 维度 | 配置 | 值 | 说明 |
|---|---|---|---|
| 人设 | `agent_runner.config.persona.persona_id` | `example` | 群友口吻、短句、不 AI 腔 |
| 触发 | 平台唤醒 | @ 或 `/` 前缀 | 群聊默认要 @ 才会回 |
| 群聊上下文 | `provider_ltm_settings.group_icl_enable` | `true` | 注入"上次回复后"的群消息，能接梗 |
| 上下文条数 | `group_message_max_cnt` | `200` | ICL 注入上限 |
| 历史持久化 | `group_message_history_enable` | `true` | 按会话存最近消息 |
| 历史条数 | `group_message_history_max_cnt` | `200` | |
| 主动插话 | `active_reply.enable` | **`false`（暂关）** | 当前小号所在群不是测试群，避免误插话；有测试群后开启 |
| 主动插话概率 | `active_reply.possibility_reply` | `0.03` | 开启后 3%，先低后调 |
| 主动插话白名单 | `active_reply.whitelist` | `[]` | **开启时必须填测试群号**，避免全群生效 |
| 默认模型 | `agent_runner.config.model.provider_id` | `deepseek` | 短、便宜、稳；可 `/model` 切 gemini 等 |
| 模型回退 | `fallback_provider_ids` | `["gemini-3.8-flash"]` | deepseek 失败/限流时自动回退 |
| 分段回复 | `platform_settings.segmented_reply.enable` | `true` | 长回复拆成多条，像真人 |
| 分段阈值 | `words_count_threshold` | `150` | 超过才拆 |
| 分段间隔 | `interval` | `1.5,3.5` 秒 | 随机 |
| 限流 | `platform_settings.rate_limit` | 60s / 20 条 | 防刷屏兜底 |

## 2. 主动插话的前提

> 当前 `active_reply.enable=false`：小号所在的群（`<GROUP_ID>`）已被用户确认**不是测试群**，
> 在确认测试群前保持关闭，避免在真实群里误插话。
> 开启步骤：`enable=true` + `whitelist=["<测试群号>"]`，然后重启 AstrBot。

AstrBot 的主动回复要求**该会话已存在对话**（`session_curr_cid`）。所以：

1. 群里先 @ 小号一次，产生对话；
2. 之后未被 @ 的消息才可能在 3% 概率下触发主动回复。

若日志出现 `No active conversation is available for proactive replies`，按提示：
关闭「会话隔离」（配置 → 平台与消息 → 通用），或先 `/new` 建一个对话。

## 3. 调参建议（按症状）

| 症状 | 调整 |
|---|---|
| 太吵、被群友嫌 | `possibility_reply` 降到 0.01–0.02，或先关 `active_reply.enable` |
| 接不上梗、像路人 | 确认 `group_icl_enable=true`；上下文条数加到 300 |
| 回复太长、AI 味重 | 人设 prompt 里收紧句长；`segmented_reply` 阈值降到 80 |
| 刷屏风险 | `rate_limit.count` 降到 10–15；分段关闭 |
| 只在测试群整活 | `active_reply.whitelist` 填群号（字符串数组） |

## 4. 整活扩展（插件层，不动核心）

- **表情包 / 梗图**：AstrBot 插件市场搜索表情包类插件。
- **戳一戳 / 互动**：OneBot 动作类插件。
- **更强的主动插话**：`smart_wake` 类插件（关键词抽签 + 小模型判定两级漏斗），
  可在内置 3% 概率不够"聪明"时替换；内置方案先跑，避免一开始就叠复杂度。
- **内容安全**：`content_safety.internal_keywords` 已启用，后续按需加 `extra_keywords`。

## 5. 验收清单（登录 + Key 就绪后）

- [ ] 群里 @ 小号：回复短、像群友、不列点
- [ ] 连续对话：上下文记得住上文
- [ ] 不 @ 时：偶尔（约 3%）主动插话且不刷屏
- [ ] 长回复被拆成多条，间隔自然
- [ ] 群里发图/表情包：bot 能接一句
- [ ] 被要求"忽略之前设定"：不泄露 prompt
- [ ] 单群 10 分钟观察：无重复、无连发、无敏感内容

## 6. 回滚

```powershell
# 关闭主动插话与分段
# data/cmd_config.json:
#   provider_ltm_settings.active_reply.enable = false
#   platform_settings.segmented_reply.enable = false
# 或直接重跑 bootstrap 前备份的 cmd_config.json.bak
```

`data/cmd_config.json.bak` 是 bootstrap 首次运行前的备份；后续可用 `scripts/backup_data.py` 做版本化备份。
