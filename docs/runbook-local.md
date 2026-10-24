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
   pwsh -File D:\qqbot\deploy\windows\start-napcat.ps1 -KillExisting
   ```

   - 控制台会打印登录二维码；二维码同时保存到 `D:\Apps\NapCat\cache\qrcode.png`
   - 推荐打开 WebUI 扫码（二维码自动刷新）：
     `http://127.0.0.1:6099/webui?token=<见 D:\Apps\NapCat\config\webui.json>`
   - 若控制台提示「可用于快速登录的 QQ」，可直接输入序号用已保存登录态快速登录

3. **验证连接**：AstrBot 控制台应出现 `aiocqhttp(OneBot v11) 适配器已连接。`
   若没有，检查 NapCat 的 WS 客户端是否启用、URL 是否为 `ws://127.0.0.1:6199/ws`。

## LLM 配置

- 把 Key 写入仓库根 `.env`（从 `config/.env.example` 复制）：

  ```
  DEEPSEEK_API_KEY=sk-...
  ```

  修改 `.env` 后需**重启 AstrBot** 生效。
- 换模型/加 provider：
  - WebUI →「模型提供商」新增任意 OpenAI 兼容服务；
  - 群聊/私聊中（管理员）用 `/provider`、`/model` 切换。
- 不把 Key 写进 `data/cmd_config.json`；provider 的 key 使用 `$DEEPSEEK_API_KEY` 环境变量引用。

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
| NapCat 报 `未找到对应版本的偏移数据` | 登录/发消息一般仍可用；若异常，升级 NapCat |
| 端口 6199 被占用 | 查 `Get-NetTCPConnection -LocalPort 6199`，结束旧 AstrBot 进程 |
| 二维码过期 | 重新打开 NapCat WebUI 刷新，或重启 NapCat |
| 群聊不回复 | 确认已 @、平台 enable、WS 已连接、provider 有 key |

## 安全注意

- `data/` 含 WebUI 密码哈希、JWT secret、聊天记录；`.env` 含 API Key —— 均不提交 git。
- NapCat WebUI 默认无访问控制且监听所有网卡，仅限本机/内网使用；VPS 必须加防火墙。
- 小号有风控风险：控制发言频率、避免敏感内容、先养号。
