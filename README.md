<div align="center">

<h1>groupmind</h1>

<p><b>A group-chat companion bot with long-term memory · research prototype</b></p>

<p>
<a href="LICENSE"><img alt="License: Apache-2.0" src="https://img.shields.io/badge/license-Apache--2.0-blue?style=flat-square"></a>
<img alt="Python 3.12 | 3.13" src="https://img.shields.io/badge/python-3.12%20%7C%203.13-3776AB?style=flat-square&logo=python&logoColor=white">
<img alt="OneBot v11" src="https://img.shields.io/badge/OneBot-v11-black?style=flat-square">
<img alt="Status: research prototype" src="https://img.shields.io/badge/status-research%20prototype-orange?style=flat-square">
</p>

<p><b>简体中文</b> | <a href="README.en.md">English</a></p>

</div>

**groupmind 是一个 AI RolePlay 方案**大体包含这几个基本功能
记忆：原文分块和检索，长期记忆与印象
联网模块：提升读取网页时面对反爬的通过率
会话接力：当模型被长工具调用卡住时，通过新的会话解决被卡住的旧会话无法回复群聊信息的问题
围绕这个目标，项目还做了一组中文群聊长期记忆的实验。

> **这是一个半成品。** 机器人在影子模式下跑通了（它准备说的话只记下来，不发进群），记忆研究有比较完整的实验记录；但它**从没在真实的群里发过言**，部署也没有收尾，只在我们自己的环境里跑过，很难直接照着跑起来。目前不打算处理部署问题，后续再继续改进。

## 它能做什么

| 能力 | 怎么做 | 状态 |
|---|---|---|
| **长期记忆** | 原始消息全部存进 SQLite；模型把消息「上色」成微语境片段，摘要和原文块各建关键词和向量索引，四路检索融合后**只把原文交给模型**；还没上色的近期消息按关键词逐条找 | 已实现；检索方案在开发集上验证，独立测试集未验证；上线后的自动上色已实现、默认关闭，未在真实数据上跑过 |
| **会话管理** | 每个群一个长会话；系统提示固定不变以命中缓存，新认识的人和后台结果追加在下一轮开头；上下文快满时，由带人设的模型自己写「给自己看的备忘」来压缩 | 已实现，影子测试中运行 |
| **会话接力** | 看视频、要开浏览器读网页这类慢任务，留在旧会话里做完；宿主复制出新会话接着聊群，旧会话的结果引用原消息回到群里，并作为内部记录交给新会话 | 已实现，有端到端测试；超过 5 分钟的工具调用会失败 |
| **联网模块** | 另开一段不带人设的对话去搜索、读网页，只交回结论；读网页从读页接口、带浏览器指纹的请求逐级升级到真 Chrome，提升面对反爬时的通过率；带 SSRF 防护 | 已实现，影子测试中运行 |
| 看视频 | 下载、压缩、切片后交给视频模型 | 已实现；QQ 里直接发的视频文件未在真实消息上测过 |
| 认识人、懂梗 | 按稳定账号识别人，记外号、印象和态度；通用梗和本群梗分两层，梗表经人工确认 | 已实现；自己记人的质量未评估，梗的候选挖掘仍是瓶颈 |
| 事件层、印象形成、回忆策略层 | 见研究报告 | 研究原型，未接入机器人 |
| 主动发话 | — | 没有 |

## 几个与众不同的设计

- **原文是事实来源，摘要只是检索入口。** 摘要、颜色、人物、梗都是可以重建的派生物；回答时交给模型的永远是原话。
- **找得浅，反而找得准。** 四路检索各取前 5 个候选再融合；取得更多，反而会让只在一路排第一的关键证据被挤出预算。
- **前缀不动，变化追加。** 人物表只在缓存前缀反正要重建时更新，后台结果作为「内部记录」放进下一轮，不插进正在进行的请求。
- **慢的事离开说话的会话。** 会话接力让「在场」和「做事」不再互相阻塞。

每个机制的数据结构、执行顺序、失败处理和代码入口，见 **[架构介绍](docs/overview/architecture.md)**。

## 研究结论

常见的角色扮演记忆是「历史对话 → 摘要 → 摘要的向量索引 → 检索摘要并注入」。groupmind 改为保留原文，并把检索拆成三层分别衡量。在两个真实开发群（约 1.6 万和 4.6 万条消息）、876 道跨周问答题上：

- **原文注入**：检索方式不变，只把交给模型的内容从摘要换成原文，准确率高 17.5 和 9.8 个百分点。
- **多路检索**：在颜色块之上加入摘要路和向量路、每路只取 5 个候选，累计提高 8.4 和 14.6 个百分点，是贡献最大的一层。
- **上色作为分块方式**：同预算下比 10 条消息的窗口高 4.1 和 2.6 个百分点，证据较弱；而且模型几乎不给一条消息上多个颜色，把颜色合并成长块反而显著变差。
- **瓶颈在找到证据**：证据进入上下文后，模型答对约 93–95%。
- **模型基本不懂本群的梗**，给一段语境也没用。

所有结论都来自开发集，冻结版还没有在独立测试集上验证；「像不像人」的部分还没有人工盲评。概念解释、每组实验的假设、控制条件和局限，见 **[研究报告](docs/overview/research-report.md)**。

## 现状与部署

- 只在一种环境里跑过：Windows PC 上一个单独的 WSL 发行版，配合计划任务和手工推送更新的脚本。没有容器镜像；隔离主要靠单独的发行版、普通用户和「shell 只写工作区」，没有容器沙箱。
- 依赖 [dsh](https://www.npmjs.com/package/@deepseek-ai/dsh) 0.2.1-rc.4 的内部接口；协议端只试过 SnowLuma（OneBot v11）。
- 测试不需要真实账号和模型（用假模型和假 OneBot）：`python -m pytest -q tests/bothost tests/bench`，其中 `tests/bothost` 需要 dsh 0.2.1-rc.4 在 PATH 上。

<details>
<summary>部署细节与目录结构</summary>

- 模型地址和密钥通过配置和环境变量传入，模板在 `deploy/wsl/config.example.json`，字段说明在 `bothost/config.py`。部分脚本里的默认地址是占位符 `<GATEWAY_HOST>`，需要自行设置。
- 当前的部署步骤见 [deploy/wsl/README.md](deploy/wsl/README.md)。`deploy/windows`、`deploy/linux` 和 `scripts/bootstrap_*` 是 AstrBot 时代的，已不适用。

| 目录 | 内容 |
|---|---|
| `bothost/` | 机器人宿主：OneBot 收发、每群一个 agent 会话、MCP 工具、会话接力、认识人 |
| `deploy/dsh/` | agent 内核（dsh）的补丁和插件：会话接力、带人设的压缩 |
| `deploy/wsl/` | 当前的部署脚本和模板（Windows + WSL） |
| `plugins/` | 读网页、看视频的读取器（目录名是 AstrBot 时代留下的） |
| `bench/` | 记忆研究台：导入、上色、检索、评测、判分、台账 |
| `scripts/memory/` | 人物和梗的快照、检索命令行 |
| `tests/` | `tests/bothost`（带假模型和假 OneBot）、`tests/bench` |
| `docs/` | 设计、研究、交接。带「已过时」标记的是 AstrBot 时代的文档 |

</details>

## 继续阅读

| 想了解 | 读 |
|---|---|
| 为什么这样设计 | [架构介绍](docs/overview/architecture.md) |
| 实验做了什么、能信到什么程度 | [研究报告](docs/overview/research-report.md) |
| 当前系统、代码地图、已知问题 | [docs/handover-2026-11-16.md](docs/handover-2026-11-16.md) |
| 每个决定的来龙去脉 | [DECISIONS.md](DECISIONS.md) |
| 按时间的开发记录 | [PROJECT.md](PROJECT.md) |

## 数据与隐私

- 真实聊天记录、人设、人工标注和密钥都**不在仓库里**。
- 代码、测试和文档里不放真实聊天内容、QQ 号和群号。群一律用 6 位代号，文档里的数字都是汇总统计，举例用的对话都是虚构的。
- 历史提交中出现过的账号、群号、群名和部分基础设施地址，已在公开前统一替换为占位符（如 `<ADMIN_QQ>`、`<GROUP_ID>`、`<GATEWAY_HOST>`）。

## 许可证

[Apache-2.0](LICENSE)
