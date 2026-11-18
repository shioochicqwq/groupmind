# groupmind

一个以「群友」身份待在 QQ 群里的聊天机器人，以及围绕它做的中文群聊长期记忆研究。

> **这是一个半成品。** 研究部分有比较完整的实验记录；机器人宿主能跑通影子测试，但从没有在真实的群里发过言。项目在半途公开，部署和兼容性都没有收尾：部署方式依赖作者自己的环境，**很难直接照着跑起来**。目前不打算处理这个问题，后续再继续改进。

## 先读这两篇

- **[架构介绍](docs/overview/architecture.md)**：一个「有记忆的群友」是怎么搭起来的。包括消息路径、记忆的三层数据、上色与冻结版检索管线、会话压缩与接力、工具，以及现状与限制。
- **[研究总结](docs/overview/research-report.md)**：中文 QQ 群聊长期记忆的实验结论和参考文献。

## 几个主要结论

在两个真实开发群（约 1.6 万和 4.6 万条消息）、876 道跨周问答题上：

- **交给模型的必须是原文。** 只给摘要比给原文块低 10–21 个百分点。
- **四路检索 + 浅候选。** 摘要和原文各用 BM25 和向量检索，RRF 融合、每路只取前 5，比同预算的固定窗口基线高 12.5 和 17.2 个百分点。每路取 20 个以上候选反而显著变差。
- **瓶颈在「找到」，不在「用好」。** 证据进入上下文后，模型能答对约 93–95%。
- **模型基本不懂本群的梗**，给一段语境也没用，必须靠梗表；而梗表的召回又是下一步的主要瓶颈。
- **「像人」要换一把尺子。** 人回忆对话是「记得少，但记得的基本是对的」。印象形成和回忆策略层的机制能跑通，但还没有用人工盲评验证。

所有结论都来自开发集，冻结版还没有在独立测试集上验证。

## 目录

| 目录 | 内容 |
|---|---|
| `bothost/` | 机器人宿主：OneBot 收发、每群一个 agent 会话、MCP 工具、会话接力、认识人 |
| `deploy/dsh/` | agent 内核（dsh）的补丁和插件：会话接力 `handoff.mjs`、带人设的压缩 |
| `deploy/wsl/` | 当前的部署脚本和模板（Windows + WSL） |
| `plugins/` | 读网页、看视频的读取器（目录名是 AstrBot 时代留下的，bothost 直接 import） |
| `bench/` | 记忆研究台：导入、上色、检索、评测、判分、台账 |
| `scripts/memory/` | 人物和梗的快照、检索命令行 |
| `tests/` | `tests/bothost`（宿主，带假模型和假 OneBot）、`tests/bench` |
| `docs/` | 设计、研究、交接。带「已过时」标记的是 AstrBot 时代的文档 |

更多入口：

- 当前系统、代码地图、已知问题：[docs/handover-2026-11-16.md](docs/handover-2026-11-16.md)
- 每个决定的来龙去脉：[DECISIONS.md](DECISIONS.md)（D-001 至 D-056）
- 按时间的开发记录：[PROJECT.md](PROJECT.md)
- 部署（Windows PC + WSL）：[deploy/wsl/README.md](deploy/wsl/README.md)

## 关于部署

请先读架构介绍的「现状与限制」一节。简单说：

- 当前只在一种环境里跑过：Windows PC 上的 WSL 发行版，配合计划任务和手工推送更新的脚本。
- 依赖 [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) 0.2.1-rc.4 的内部接口，换版本要重新验证。
- 协议端只试过 SnowLuma（OneBot v11）。
- 模型地址、密钥都通过配置和环境变量传入，模板在 `deploy/wsl/config.example.json`，字段说明在 `bothost/config.py`。部分脚本里的默认地址是占位符 `<GATEWAY_HOST>`，需要自行设置。
- `deploy/windows`、`deploy/linux` 以及 `scripts/bootstrap_*` 是 AstrBot 时代的，已不适用。

测试不需要真实账号和模型（用假模型和假 OneBot）：

```bash
python -m pytest -q tests/bothost tests/bench
```

`tests/bothost` 需要 `dsh` 0.2.1-rc.4 在 PATH 上。

## 数据与隐私

- 真实聊天记录、人设、人工标注、密钥都**不在仓库里**。
- 代码、测试、文档里不放真实聊天内容、QQ 号和群号。群一律用 6 位代号；文档里的数字都是汇总统计。
- 历史提交中出现过的账号、群号、群名和部分基础设施地址，已经在公开前统一替换为占位符（如 `<ADMIN_QQ>`、`<GROUP_ID>`、`<GATEWAY_HOST>`）。
