# 上下文与记忆机制

> 目标：让 bot 在私聊/群聊里「记得住上文、接得上梗」，同时不无限膨胀、不串会话。
> 对应配置由 `scripts/bootstrap_astrbot_config.py` 写入 `data/cmd_config.json`。

## 1. 会话隔离

- AstrBot 以 `umo`（unified message origin）区分会话：`平台:消息类型:会话 ID`，
  例如私聊 `napcat:FriendMessage:<ADMIN_QQ>`，群聊 `napcat:GroupMessage:<群号>`。
- 私聊/各群各自独立上下文；`platform_settings.unique_session=false`（群内多人共享同一群上下文，符合群聊直觉）。
- 管理员可用 `/reset` 清空当前会话上下文（QQ 主号已在 `admins_id`）。

## 2. 群聊上下文（接梗关键）

| 机制 | 配置 | 当前值 | 作用 |
|---|---|---|---|
| ICL 注入 | `provider_ltm_settings.group_icl_enable` | `true` | 把「上次回复后」的群消息拼进本次 LLM 请求 |
| ICL 条数 | `group_message_max_cnt` | `200` | 注入上限 |
| 历史持久化 | `group_message_history_enable` | `true` | 存最近群消息，供工具检索 |
| 历史条数 | `group_message_history_max_cnt` | `200` | |
| 图片描述 | `image_caption` + `image_caption_provider_id` | `true` / `gemini-3.8-flash` | 群里图片转一句中文描述再进上下文 |

另有工具 `get_group_message_history`（默认激活）：当用户提到「之前说过的」而自动上下文不够时，
模型可主动检索当前群的历史消息。

## 3. 私聊上下文

- 常规多轮对话：AstrBot 按会话保存历史并随请求带上（受模型上下文窗口约束）。
- 已实测：同一会话「记住：我叫小明，喜欢打游戏」→「我叫什么？喜欢干嘛？」→ 正确回答。
- `/reset` 可清空。

## 4. 上下文压缩（防爆窗口）

`agent_runner.config.compression` 当前为默认策略：

```json
{
  "max_turns": -1,
  "trim_turns": 1,
  "overflow_strategy": "llm_compress",
  "keep_recent_ratio": 0.15,
  "provider_id": "",
  "fallback_max_tokens": 128000
}
```

- 达到模型上下文上限时用 LLM 摘要压缩历史（`llm_compress`），保留最近 15% 原文；
- `provider_id` 为空 = 用默认 provider；如需更便宜可改成 `gemini-3.8-flash`；
- 不同模型窗口不同（deepseek-chat 128K，gemini/claude/gpt 聚合模型 1M 左右），压缩策略按窗口自适应。

## 5. 已知边界

- 群聊 ICL 的 token 成本随活跃度上升（200 条 × 每群）；群多时可降到 100。
- 私聊/群聊记忆只在本地 `data/data_v4.db`；迁移 VPS 时随 `data/` 一起搬。
- 没有跨会话的长期记忆（如「记住我是谁」全局生效）——如果需要，可后续用知识库或 `future_task`/cron 方案。
- 主动插话仍关闭（等测试群），因此「群聊上下文」目前只在被 @ 时参与。
