# Skill 开发教程（从 0 到能用 + 人味）

> **已过时（2026-11-16）**：本文是 AstrBot 时代的文档。机器人现在是 `bothost` + dsh，部署在 Windows PC 的 WSL 里。当前状态见 [handover-2026-11-16.md](handover-2026-11-16.md)，本文只作历史参考。

> 配套：[skills-dev.md](skills-dev.md)（格式/工具清单）、[skills/web-lookup](../skills/web-lookup/SKILL.md)、
> [skills/style-humanizer](../skills/style-humanizer/SKILL.md)、[scripts/install_skill.py](../scripts/install_skill.py)。
> 前提：已开启 `computer_use_runtime=local`（只开放 workspace），否则模型读不到 `SKILL.md` 正文，技能不会真正生效。

## 第 0 步：搞清 Skill 是什么

Skill = 一份给模型的「操作说明书」+ 需要时引用的资料/脚本。
AstrBot 只在系统提示里放**名字和 description**；模型决定用某个技能后，再用文件工具读取
`data/skills/<name>/SKILL.md` 正文（渐进披露，省 token）。所以：

- 写不好 description = 永远不会被触发；
- 没有文件工具 = 永远读不到正文。

## 第 1 课：最小可用 Skill（10 分钟）

1. 建目录（名字只能小写字母/数字/连字符）：
   ```
   skills/hello/SKILL.md
   ```
2. 写内容：
   ```markdown
   ---
   name: hello
   description: 当用户说“用群友口吻打个招呼”或要求生成一句简短问候时使用。
   ---

   # 群友打招呼

   1. 用 1 句话打招呼，≤ 20 字。
   2. 口语化，不用“您好/很高兴”。
   3. 最多带 1 个 emoji。
   ```
3. 安装 + 重启：
   ```powershell
   python scripts\install_skill.py hello --force
   # 重启 AstrBot
   ```
4. 验证：私聊发「用群友口吻跟我打个招呼」；日志里能看到读文件/最终回复符合规则。
   不符合时先检查：description 是否覆盖触发说法、`SKILL.md` 是否被读到（日志/工具调用）。

**常见错误**

| 现象 | 原因 |
|---|---|
| 从不触发 | description 写得太泛或没写触发场景 |
| 触发了但不遵守 | 规则不具体、正文太长、多个目标冲突 |
| 目录名与 name 不一致 | `install_skill.py` 会直接报错 |

## 第 2 课：触发设计与工具

**description 公式**：`能力 + 具体触发说法/场景`。例：
> 查当前/最近信息（新闻、发布、价格、版本等），当用户要求“查一下/搜一下/最新/最近”或需要核实时效信息时使用。

**可用工具**（取决于配置）：

| 工具 | 用途 | 当前状态 |
|---|---|---|
| `web_search_deepseek` / `deepseek_fetch_web_page` | 搜索 / 读整页 | 已启用 |
| `astrbot_file_read_tool` | 读收到的文件（txt/pdf/docx/epub/图片） | 已启用（workspace） |
| `memory_write/read/search/edit` | 记忆本子 | 已启用（memory_beyond） |
| `get_group_message_history` | 查群历史 | 已启用 |
| `send_message_to_user` | 主动发消息/媒体 | 已启用 |
| shell / python / 浏览器 | 执行代码/浏览器 | **不可用**（权限关闭） |

**练习**：给「读文件」写一个技能——用户发文件并说「总结一下」时，先读文件、再按 3 条以内要点回答，
读不到就如实说，不要编。写好后用 `--no-stream` smoke 测试。

## 第 3 课：人味 Skill + 语料

人味不是一句“要自然”，而是可执行的规则 + 示例：

1. **规则**：句长、标点、口头禅、接梗方式、拒绝方式、边界（见 [style-humanizer](../skills/style-humanizer/SKILL.md)）；
2. **few-shot**：从语料挑 20–40 条真实短对话，放 `references/examples.md`，只在需要时读；
3. **评测**：30–50 条输入，人评「像不像群友 / 是否有 AI 腔 / 是否接得住」；改一版测一版；
4. **不要**一开始就微调；few-shot + 规则迭代 2–3 轮后再评估。流程见 [corpus-and-style.md](corpus-and-style.md)。

**练习**：把下面这句改得有群友味，写成技能：
> 「您好，您的问题我已经了解，稍后将为您处理，请耐心等待。」
> 目标：≤15 字、口语、带一点情绪但不冒犯。

## 调试与验收清单

- [ ] `install_skill.py` 安装成功，重启后 WebUI/Skills 或 `GET /api/v1/skills` 能看到
- [ ] 用真实触发说法能命中（不是直接点名技能）
- [ ] 模型确实读了 `SKILL.md`（日志/工具调用可见）
- [ ] 输出符合规则；失败时有兜底而不是编造
- [ ] 用 `smoke_llm.py --no-stream` 复现过至少一次
- [ ] 技能不会诱导模型读敏感文件 / 越权（workspace 之外会被拒绝）

## 参考

- AstrBot Skill 规范（兼容 Codex/Claude SKILL.md）：[skills-dev.md](skills-dev.md)
- 内置 `skill-creator` 技能：可直接对 bot 说「帮我创建一个 skill：……」，再按本教程 review
