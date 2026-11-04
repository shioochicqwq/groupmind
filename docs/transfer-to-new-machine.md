# 迁移到另一台机器（打包/恢复说明）

> 本机不能常驻时，把源码与文档打成一个 zip，上传网盘，到新机器解压恢复。
> 打包脚本：`python scripts/package_transfer.py`（默认输出到仓库同级的 `qqbot-packages/`）。

## 0. 包里面有什么 / 没有什么

**`qqbot-source-YYYYMMDD.zip`（安全，可上传）**

- 整个 git 仓库：源码、`PROJECT.md`/`DECISIONS.md`/`docs/`、`scripts/`、`skills/`、本项目插件、部署文件；
- `.git/` 历史（方便在新机器继续提交）；
- 当前工作区的 `AGENTS.md`（含你的本地修改）。

**不包含（重要）**

| 排除项 | 原因 |
|---|---|
| `.env` | LLM/API key，绝不能进网盘 |
| `data/` | AstrBot 运行时：`cmd_config.json`（含搜索 key）、聊天数据库、记忆、日志、临时文件 |
| `backups/` | 历史备份（其中还有无关项目备份） |
| `tmp/`、`.astrbot`、`astrbot.lock` | 本地临时/运行时文件 |

如果需要把**记忆/表情包数据集**也带走，用可选的 `qqbot-data-bundle-YYYYMMDD.zip`（只含非密钥数据，见第 3 节）。

## 1. 新机器前置

> 目标机器：常驻 Windows PC（D-021）。SnowLuma 相关步骤**尚未实测**，首次部署时按第 5 节验收后回填本文档。

- Windows x64，PowerShell 7（`pwsh`）、Git、Python 3.12 + `uv`；安装 AstrBot（`uv tool install astrbot --python 3.12`）；
- 桌面版 QQ（NTQQ），**关闭自动更新**；
- SnowLuma：从 [Releases](https://github.com/SnowLuma/SnowLuma/releases) 下载 `SnowLuma-v2.3.3-win-x64.zip`
  （完整版，内置 Node.js），解压到 `C:\SnowLuma`；
- **需要重新扫码登录**（QQ 登录态不在本仓库）；
- 网络能访问 LLM 端点（DeepSeek / 聚合端点）。

## 2. 恢复步骤

```powershell
# 1) 解压 zip 到例如 D:\qqbot
cd D:\qqbot

# 2) 配置密钥（从模板复制，填入你自己的 key）
Copy-Item .env.example .env
notepad .env

# 3) 生成 SnowLuma 配置，并把缺失的 ONEBOT_WS_TOKEN / SNOWLUMA_HTTP_TOKEN 写入 .env
python scripts\configure_snowluma.py

# 4) 初始化 AstrBot 数据目录，再写入配置（平台/模型/人格/记忆/文件工具/网页工具）
astrbot init -y
python scripts\bootstrap_astrbot_config.py

# 5) 安装外部依赖插件 memory_beyond（固定提交，见 docs/external-plugins.md）
git clone https://github.com/AlanBacker/astrbot_plugin_memory_beyond data\plugins\astrbot_plugin_memory_beyond
git -C data\plugins\astrbot_plugin_memory_beyond checkout 0ec75bfb1a36a416121088d19acd7027ac9c0274

# 6) 安装本项目插件 + 技能
python scripts\install_plugin.py --force
python scripts\install_skill.py --force

# 7) 启动 AstrBot，修改初始密码后写入人设
pwsh -File deploy\windows\start-astrbot.ps1
$env:ASTRBOT_DASHBOARD_PASSWORD='<WebUI 密码>'
python scripts\apply_persona.py --file config\personas\example.json

# 8) 新开一个窗口启动 SnowLuma，到 http://127.0.0.1:5099/ 确认 EULA 和隐私政策，再打开 QQ 扫码登录
pwsh -File deploy\windows\start-snowluma.ps1

# 9) 体检
python scripts\healthcheck.py

# 10) 验收通过后再开启常驻：注册计划任务，并开启 Windows 自动登录、关闭睡眠
pwsh -File deploy\windows\register-autostart.ps1
```

> 第 4 步要求 `data/cmd_config.json` 已存在，所以必须先 `astrbot init -y`。如果从 data bundle 恢复
> 记忆/数据集，先执行 bootstrap，再把 bundle 的非密钥文件覆盖进去；**不要**恢复旧 `cmd_config.json`（它含 key）。
>
> 平台 id 已从 `napcat` 改为 `snowluma`，会话键也随之改变：bundle 里 `napcat_FriendMessage_*` 的会话状态不会被新会话沿用。

## 3. 可选：数据包（记忆 / 表情包数据集）

```powershell
python scripts\package_transfer.py --data-bundle
```

生成 `qqbot-data-bundle-YYYYMMDD.zip`，只包含：

- `data/sticker_dataset/`（表情包数据集，含标注/图片）
- `data/plugin_data/`（memory_beyond 的记忆 Markdown）
- `data/config/`（插件配置，不含主配置）
- `data/skills/`、`data/mcp_server.json`、`data/skills.json`

**安全提示**：这是聊天派生数据（表情包、人物记忆），可能含他人内容/隐私；只上传到**自己的私有网盘**，
不要公开分享；介意的话可以加密压缩（7-Zip 加密码）再上传。

## 4. 上传 Google Drive

1. 上传 `qqbot-source-YYYYMMDD.zip`（以及可选的 data bundle）；
2. 记下同目录的 `.sha256` 文件内容；新机器下载后校验：
   ```powershell
   Get-FileHash qqbot-source-YYYYMMDD.zip -Algorithm SHA256
   ```
3. 不要上传：`.env`、原始 `data/`、`backups/`、`tmp/`。

## 5. 新机器验收

```powershell
python scripts\healthcheck.py     # 端口/SnowLuma/Bot/模型/记忆/文件/网页工具/表情包采集
python scripts\smoke_llm.py --no-stream --message "在吗"
```

表情包数据集：若解压了 data bundle（与 source 压缩包在同级解压，会自动合并进 `qqbot/data/`），运行
`python scripts\sticker_dataset_report.py` 查看数量；标注/评测命令见
[sticker-dataset.md](sticker-dataset.md)。
