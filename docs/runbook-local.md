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
- 主动插话需要会话已存在：先在群里 @ 小号一次。

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
