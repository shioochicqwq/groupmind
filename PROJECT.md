# qq-bot 项目开发历史与工程事件记录（PROJECT.md）

本文档记录本项目开发历史。采用**追加式事件记录**，保留历史决策及其依据。
新事件添加到事件列表，旧事件不得覆盖或删除。

---

## EVT-20261101-001：初始化项目与规范配置
- **时间**：2026-11-01T02:01:00Z
- **背景**：创建 QQ 机器人项目 `qq-bot` 并开启 Claude Code Remote 会话。
- **实施**：
  1. 初始化 Git 仓库，建立 `README.md`、`CLAUDE.md`、`AGENTS.md`。
  2. 确立统一使用 `PROJECT.md` + `DECISIONS.md`。
  3. 启动 `claude remote-control --name qq-bot --spawn same-dir` 会话服务。
- **验证**：云端会话连接成功（Connected · qq-bot · master）。
