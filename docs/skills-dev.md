# Skill 开发指南（AstrBot）

> 用户计划自行编写 Skill；本仓库把 Skill 当代码管理：`skills/` 为源，安装到 `data/skills/`。
> AstrBot 版本：4.29.1；技能格式与 OpenAI Codex / Claude Skills 兼容。

## 1. 格式

`skills/<name>/SKILL.md`，YAML frontmatter 只能有 `name` 和 `description`：

```markdown
---
name: web-lookup
description: 什么时候该用这个技能（触发条件写清楚，AstrBot 只先看这段决定是否加载）
---

# 标题

给模型的指令：步骤、工具名、输出约束、失败处理。
```

规则（来自内置 `skill-creator`）：

- 目录名必须与 frontmatter `name` 一致；小写字母/数字/连字符。
- 描述写「能力 + 触发场景」，因为模型先只看 `description`，加载后才读正文（渐进披露）。
- 正文用祈使句，把主流程写在前面；需要时再放 `scripts/`、`references/`、`assets/`。
- 不要放 README、changelog 等重复文档。

## 2. 位置与安装

| 位置 | 用途 |
|---|---|
| `skills/<name>/`（本仓库） | 源文件，进 git |
| `data/skills/<name>/`（运行时） | AstrBot 实际加载目录，gitignored |

```powershell
# 安装仓库里的全部/单个 skill
python scripts\install_skill.py
python scripts\install_skill.py web-lookup --force
# 重启 AstrBot 生效
```

仓库自带示例：[skills/web-lookup/SKILL.md](../skills/web-lookup/SKILL.md)（联网查询，配合已启用的
`web_search_deepseek` 工具）。

## 3. 写 Skill 前先确认：工具是否可用

AstrBot 已经注册但**按配置激活**的工具（详见 WebUI → 工具 或 `/api/v1/tools`）：

| 场景 | 工具 | 激活条件 |
|---|---|---|
| 联网搜索 | `web_search_deepseek` / `deepseek_fetch_web_page` | `provider_settings.web_search=true` 且 `websearch_provider=deepseek`（已启用，复用 DeepSeek key） |
| 群聊历史 | `get_group_message_history` | 默认已激活 |
| 主动发消息/媒体 | `send_message_to_user` | OneBot 平台支持主动消息（已激活） |
| 知识库 | `astr_kb_search` | 需建知识库 |
| 浏览器/沙盒执行 | `astrbot_execute_shell` 等 | `computer_use_runtime=sandbox` 且 sandbox booter 可用（本地未开） |

> 本地/当前 VPS 配置下 `computer_use_runtime=local`（只开放 workspace、禁执行），
> 模型可读 `data/skills` 与 `data/temp`（QQ 附件），但**不能 shell/浏览器/写 host**；
> Skill 应优先调用上表中的内置 function tool。教程见 [skill-tutorial.md](skill-tutorial.md)。

## 4. 调试与验收

1. 安装技能并重启 AstrBot；
2. WebUI → Skills 页或 `GET /api/v1/skills` 确认已列出；
3. 用 WebChat 模拟触发（例如「帮我查一下今天有什么 AI 新闻」），观察：
   - 回复是否走搜索（内容足够新）；
   - 是否遵守「简短 + 来源」的输出约束；
   - 失败时是否诚实说明而不是编造；
4. 也可用 `scripts/smoke_llm.py --message "..."` 做单条验证；
5. **验证发送前处理（如 <ref> 剥离）用 `--no-stream`**：QQ/OneBot 是非流式路径，
   WebChat 默认流式会绕过部分装饰阶段，`--no-stream` 更接近真实行为。

```powershell
python scripts\smoke_llm.py --provider deepseek --no-stream --message "帮我查一下 DeepSeek V4 哪天发布的"
```

## 4.1 插件：剥离 <ref> 引用标记

AstrBot 联网搜索会要求模型输出 `<ref>index</ref>` 引用格式，QQ 里会显示成乱码。
仓库插件 [plugins/astrbot_plugin_strip_refs](../plugins/astrbot_plugin_strip_refs/main.py) 在
`on_decorating_result` 阶段把标签去掉（不改核心）：

```powershell
python scripts\install_plugin.py --force   # 复制到 data/plugins 并重启 AstrBot
```

> 注意：流式输出平台（WebChat）在流式阶段可能绕过该钩子；QQ/OneBot 非流式，正常生效。

## 5. 用 AstrBot 自己写 Skill

AstrBot 自带 `skill-creator` 技能（内置）。在私聊里直接说「帮我创建一个 skill：……」，它会指导
生成/校验 SKILL.md；沙盒模式下还可通过 `astrbot_create_skill_payload` 等工具发布。本地模式下
推荐按本文手动写、用 `install_skill.py` 安装——可版本化、可 review。

## 6. 本次启用的相关能力（2026-10-24）

- **联网搜索**：`web_search_deepseek`，复用 `DEEPSEEK_API_KEY`（已实测 `api.deepseek.com/v1/tools/search` 返回结果）；
- **多模态**：图片 caption 用 `gemini-3.8-flash`（视觉），群聊上下文里的图片会转成一句中文描述；
- **上下文**：群聊 ICL（最近 200 条）+ `get_group_message_history` 工具 + 自动上下文压缩；
- 现有示例技能：`web-lookup`。
