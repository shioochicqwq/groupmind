# qq-bot

一个以「群友」身份在 QQ 群里聊天的机器人，以及它的长期记忆研究。

- **从这里开始**：[docs/handover-2026-11-16.md](docs/handover-2026-11-16.md)，交接总入口，讲系统结构、东西都在哪、怎么跑、没做完的事和规矩。
- 状态和变更记录：[PROJECT.md](PROJECT.md)；决策：[DECISIONS.md](DECISIONS.md)。
- 部署（Windows PC + WSL）：[deploy/wsl/README.md](deploy/wsl/README.md)。

## 目录

| 目录 | 内容 |
|---|---|
| `bothost/` | 机器人宿主：OneBot 收发、每群一个 dsh 会话、MCP 工具、会话接力、认识人 |
| `deploy/dsh/` | dsh 补丁和插件：接力 `handoff.mjs`、人设压缩 |
| `deploy/wsl/` | 当前部署脚本和模板 |
| `plugins/` | 读网页、看视频的读取器（目录名是 AstrBot 时代的，bothost 直接 import） |
| `bench/` | 记忆研究：消息库、检索、上色、评测、账本 |
| `scripts/memory/` | 人物和梗的快照、检索命令行 |
| `tests/` | `tests/bothost`（宿主，带假模型和假 OneBot）、`tests/bench` |
| `docs/` | 设计、研究、交接；带「已过时」标记的是 AstrBot 时代的文档 |

真实聊天数据、人设、密钥都不在仓库里，在同级的 `qqbot-data/`，见交接文档第 4 节。

```bash
../qqbot-data/venv/bin/python -m pytest -q tests/bothost tests/bench
```
