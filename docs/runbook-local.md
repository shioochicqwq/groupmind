# 本地运行手册（Windows）

## 前置条件

- Windows + 已安装 QQNT（`C:\Program Files\Tencent\QQNT`）
- `uv`（已装）；AstrBot 已通过 `uv tool install astrbot --python 3.12` 安装（v4.29.1）
- NapCat 位于 `D:\Apps\NapCat`（复用既有安装）
- 仓库根目录 `D:\qqbot`

## 启动顺序

1. **启动 AstrBot**（会加载 `.env`，避免日志乱码）：

   ```powershell
   pwsh -File D:\qqbot\deploy\windows\start-astrbot.ps1
   ```

   - WebUI：`http://127.0.0.1:6185`，用户名 `astrbot`
   - 初始密码见第一次启动日志，**首次登录后立即修改**
   - OneBot 反向 WS 监听：`0.0.0.0:6199`（路径 `/ws`）

2. **启动 NapCat**（会自动结束已存在的 QQ 进程）：

   ```powershell
   # 首次 / 设备或版本变化后：扫码登录
   pwsh -File D:\qqbot\deploy\windows\start-napcat.ps1 -KillExisting

   # 已保存登录态时：尝试快速登录（可能仍要求手机 QQ 验证，则回退扫码）
   pwsh -File D:\qqbot\deploy\windows\start-napcat.ps1 -QuickLogin <BOT_QQ>
   ```

   - 控制台会打印登录二维码；二维码同时保存到 `D:\Apps\NapCat\cache\qrcode.png`
   - 推荐打开 WebUI 扫码（二维码自动刷新）：
     `http://127.0.0.1:6099/webui?token=<见 D:\Apps\NapCat\config\webui.json>`
   - **NapCat 版本**：当前 v4.18.41（2026-10-24 从 4.18.28 升级，修复 QQ 9.9.32 Packet 兼容问题）。
     旧安装备份在 `D:\Apps\NapCat.bak-*`。
   - 升级 NapCat 时：停 QQ/NapCat → 解压新版 `NapCat.Shell.zip` 覆盖安装目录（**保留 `config/`**）
     → 重新执行 `python scripts\patch_napcat_onebot.py` → 扫码登录。
   - 启动脚本会把工作目录切到 `D:\Apps\NapCat`，避免 QQ 在仓库根写 `guild*.db`。

3. **验证连接**：AstrBot 控制台应出现 `aiocqhttp(OneBot v11) 适配器已连接。`
   若没有，检查 NapCat 的 WS 客户端是否启用、URL 是否为 `ws://127.0.0.1:6199/ws`。

## LLM 配置

- 把 Key 写入仓库根 `.env`（从仓库根 `.env.example` 复制）：

  ```
  DEEPSEEK_API_KEY=sk-...
  ```

  修改 `.env` 后需**重启 AstrBot** 生效。
- 换模型/加 provider：
  - WebUI →「模型提供商」新增任意 OpenAI 兼容服务；
  - 群聊/私聊中（管理员）用 `/provider`、`/model` 切换。
- 不把 Key 写进 `data/cmd_config.json`；provider 的 key 使用 `$DEEPSEEK_API_KEY` / `$MULTI_API_KEY` 环境变量引用。

### 模型冒烟测试（不依赖 QQ 群）

```powershell
$env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
$env:PYTHONIOENCODING='utf-8'
python scripts\smoke_llm.py --provider deepseek
python scripts\smoke_llm.py --provider gemini-3.8-flash --message "用一句话吐槽今天的天气"
# 验证多轮上下文（同一会话发第二条）
python scripts\smoke_llm.py --provider deepseek --message "记住：我叫小明，喜欢打游戏" --followup "我叫什么？喜欢干嘛？"
```

已配置模型：`deepseek-chat`（默认）、`gemini-3.8-flash`、`claude-sonnet-4-6`、
`claude-opus-4-6`、`gpt-6-astra`、`gpt-6.1-sol`（自定义聚合端点，见 `.env` 的 `MULTI_API_BASE`）。
群聊/私聊里管理员可用 `/provider`、`/model` 切换。

## 人格与群聊整活

- 人设源文件：`config/personas/example.json`；写入 AstrBot：

  ```powershell
  $env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
  python scripts\apply_persona.py --file config\personas\example.json
  ```

- 群聊触发/主动插话/分段/限流等参数由 `scripts/bootstrap_astrbot_config.py` 管理，
  调整后重启 AstrBot；调参说明与验收清单见 [group-chat-tuning.md](group-chat-tuning.md)。
- 人设评测（没有测试群时用 WebChat 模拟群聊场景）：

  ```powershell
  $env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
  $env:PYTHONIOENCODING='utf-8'
  python scripts\eval_persona.py --provider deepseek
  ```

  结果记录：[persona-eval.md](persona-eval.md)。
- 主动插话需要会话已存在：先在群里 @ 小号一次。当前默认关闭，等测试群再开。

## 一键体检

```powershell
$env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
python scripts\healthcheck.py
```

检查：4 个端口、NapCat 登录/在线状态、AstrBot 平台适配器、6 个 LLM provider、人格。
全部 PASS 退出码为 0；任何 FAIL 退出码 1（VPS 上同样适用，日志用 journalctl 对照）。

## 联网搜索 / 多模态 / Skill / 插件

```powershell
# 安装仓库里的 skills 和 plugins 到 data/（gitignored），然后重启 AstrBot
python scripts\install_skill.py --force
python scripts\install_plugin.py --force

# 联网搜索验证（--no-stream 更接近 QQ 非流式路径）
$env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
python scripts\smoke_llm.py --provider deepseek --no-stream --message "帮我查一下 DeepSeek V4 哪天发布的"
```

- 联网搜索：`web_search_deepseek`，复用 `DEEPSEEK_API_KEY`；新增 Skill 见 [skills-dev.md](skills-dev.md)。
- 多模态：图片 caption 用 `gemini-3.8-flash`，群聊图片会转一句中文描述（消耗视觉 token）。
- 引用标记 `<ref>` 由插件 `astrbot_plugin_strip_refs` 在发送前剥离（仅非流式；QQ 正常生效）。

## 记忆本子（memory_beyond）

- 插件版本/配置/升级：见 [external-plugins.md](external-plugins.md)；数据在
  `data/plugin_data/astrbot_plugin_memory_beyond/`。
- 私聊验证：

  ```powershell
  # 在 QQ 私聊里对 example 说：记住：我叫小明，喜欢打游戏
  # 然后发 /reset 清会话，再问：我叫什么？喜欢干嘛？
  # 管理员指令：
  /mb_status    # 记忆/压缩状态、token 分项
  /mb_probe     # 摘要链路自检
  ```

- WebUI 侧边栏「插件页面 → 记忆管理」可查看/编辑/整理记忆。
- 只跑命令不测 QQ 时：`python scripts\smoke_llm.py --no-stream --message "..."` + `/mb_status`。

## 文件工具（读你发给 bot 的文件）

- 配置：`computer_use_runtime=local`，member/admin 均 workspace、禁执行/禁网络（D-014）。
- 把你发的 `.txt/.pdf/.docx` 直接发给 example，附一句「总结这个文件」；AstrBot 会把
  `[File Attachment: name, path]` 注入，模型用 `astrbot_file_read_tool` 读 `data/temp`。
- 越权测试：让它读 `D:\qqbot\PROJECT.md`，应被权限拒绝（只允许 workspace/技能/临时目录）。
- 手动验证（不依赖 QQ）：

  ```powershell
  Set-Content data\temp\test.txt "暗号是蓝色海豚 42" -Encoding UTF8
  # WebChat 里发：读取 D:\qqbot\data\temp\test.txt，暗号是什么
  ```

## 表情包数据集（只采集，不发送）

```powershell
# 私聊/群聊里发表情包（插件自动采集候选）；管理员可引用图片发：
/sticker add
/sticker status

# 标注 + 统计/复核 + 评测
python scripts\label_sticker_dataset.py --limit 20
python scripts\sticker_dataset_report.py --review-csv
python scripts\eval_sticker_understanding.py --limit 10
```

- 数据在 `data/sticker_dataset/`（gitignored）；格式/标注规范见 [sticker-dataset.md](sticker-dataset.md)。
- 插件无发送工具，模型不会发表情包；普通照片默认不收，只收 `sub_type=1`/`[动画表情]`/GIF。
- 不装 stealer 等带发送功能的插件（D-018）。

## 网页读取

- 工具：`web_reader`（本项目插件，本地抓取，返回正文+页面链接）；`web_search_deepseek` 负责搜索；
  DeepSeek 的 `deepseek_fetch_web_page` 保留为 fallback。
- 验证：

  ```powershell
  # WebChat 或 QQ 私聊里发：
  # 帮我看看 https://whatasiger.xyz/carrier_wave/ 这个页面写了什么
  # 再看看 https://whatasiger.xyz/ 里有什么文章，挑一篇讲讲
  ```

- 行为：首页/目录页会返回链接列表，模型可挑文章再读；长文可用 `offset` 续读；
  读不到时允许模型自然推脱（网不好/等会儿），但不能编造。
- 限制：JS 渲染站、登录墙、强反爬页面可能拿不到正文；此时可换链接或改用第三方 reader（D-017）。
- 安全：`web_reader` 只允许 http/https，拒绝 localhost/内网/私有 IP（含重定向逐跳校验）。

## 掉线 / 漏消息恢复

- 现象：NapCat 日志出现 `[KickedOffLine] 你的账号当前登录已失效`，端口 3000 消失、bot 不回消息。
  通常是**同账号在别的设备/客户端登录**或 QQ 安全验证导致。
- 恢复：打开 `http://127.0.0.1:6099/webui?token=<token>` 扫码重登（选对应小号），
  等 AstrBot 日志重新出现「适配器已连接」，再跑 `scripts/healthcheck.py`。
- **补回漏掉的消息**：重登后离线期间的消息不会进 AstrBot，可用 NapCat 的
  `get_friend_msg_history` / `get_group_msg_history` 拉最近消息，再按人设手动补回复
  （本项目 2026-10-24 已用该方式补回两条）。
- 预防：小号只给 NapCat 用，不在手机/其他 PC 客户端同时登录；保持扫码环境固定。

## 群聊测试

- 小号加入测试群（建议自己建的小群）；
- 群内 `@小号 你好`，应收到回复；
- 默认群聊上下文携带最近 200 条群消息（`provider_ltm_settings`）。

## 停止与重启

- AstrBot：终止 `python.exe`（AstrBot）进程后重新运行启动脚本；
- NapCat：结束 `QQ.exe` / `NapCatWinBootMain.exe` 后重新运行启动脚本；
- 两者均无服务化守卫，VPS 阶段改由 Docker Compose 的 `restart: unless-stopped` 负责。

## 常见问题

| 现象 | 处理 |
|---|---|
| AstrBot 日志 `references environment variable ... not set` | `.env` 未配置对应 key，配置后重启 |
| Provider 初始化失败 `Missing credentials` | 同上 |
| NapCat 报 `未找到对应版本的偏移数据` / `PacketBackend 不支持当前QQ版本架构` | NapCat 与 QQ 版本不匹配；查 NapCat release 兼容表并升级 NapCat（D-008） |
| NapCat 升级后快速登录提示「登录需要手Q验证」 | 正常设备校验，改用二维码扫码登录 |
| 端口 6199 被占用 | 查 `Get-NetTCPConnection -LocalPort 6199`，结束旧 AstrBot 进程 |
| 二维码过期 | 重新打开 NapCat WebUI 刷新，或重启 NapCat |
| 群聊不回复 | 确认已 @、平台 enable、WS 已连接、provider 有 key |

## 安全注意

- `data/` 含 WebUI 密码哈希、JWT secret、聊天记录；`.env` 含 API Key —— 均不提交 git。
- NapCat WebUI 默认无访问控制且监听所有网卡，仅限本机/内网使用；VPS 必须加防火墙。
- 小号有风控风险：控制发言频率、避免敏感内容、先养号。
