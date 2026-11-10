# 联网搜索与视频理解模块 · P0 审计与冒烟（2026-11-07）

> 对应计划书《QQBot / RP Agent 联网搜索与视频理解模块计划书》v0.1 的 P0。本轮在云端开发容器里做，**不是**机器人实际运行的 Windows 机器。

## 1. 结论先行

- **P0 未通过退出条件**，原因有两个，都不是代码缺陷：
  1. 在本环境运行第三方代码（`npm ci` 及其安装脚本，以及 Crawl4AI 的安装）被权限规则拦下。是否放开要由用户决定，见第 6 节。
  2. 从本容器访问时，B 站所有公开接口都返回 **HTTP 412**（平台拒绝），萌娘百科、百度百科、知乎返回 **403**。这很可能是机房 IP 被风控，**结论不能代表实际运行环境**。真实可用性要在机器人所在机器上复测。按计划书要求，没有尝试任何规避。
- 项目已有可用的搜索和网页读取：AstrBot 内置 `web_search_deepseek`（DeepSeek `tools/search`，D-012），以及自研的 `web_reader`（requests + bs4，带 SSRF 防护）。计划书 P1 的 `search_web` 应先包装这两者，不需要新的搜索服务。本容器里没有 DeepSeek 密钥，搜索本身这次没测。

## 2. 固定的上游版本

| 项目 | 提交 | 日期 | 许可 | 备注 |
|---|---|---|---|---|
| Bilibili-Video-Research（BVR） | `db78c19f9ac2` | 2026-11-06 | MIT | 18 星，共 63 个提交，仍在快速变动；包名 `bilibili-video-research-mcp` 0.1.0 |
| Crawl4AI | `cae74b203a33` | 2026-11-04 | Apache-2.0 | 本轮未安装 |
| dsh-qq-relay | `71fb7a39c00a` | 2026-10-24 | MIT | 仅参考 |

BVR 已克隆到仓库外的 `qqbot-data/vendor/bvr`（检出上面的提交），只做了静态阅读，没有安装或运行。

## 3. BVR 静态审计

**依赖**：Node ≥ 24（本机 v24.19.0）；`@google/genai`、`@modelcontextprotocol/sdk`、`ffmpeg-static`、`yt-dlp-exec`、`zod`、`dotenv`。`ffmpeg-static` 和 `yt-dlp-exec` 在安装时会下载二进制文件。

**MCP 工具**（`src/index.ts`）：

| 工具 | 做什么 | 包装时的处理 |
|---|---|---|
| `analyze_bilibili_video` | B 站 URL（含 b23.tv）+ 问题 + `language` / `vision` / `multimodal`，可选时间段、清晰度、评论 | 主入口，包装成 `research_bilibili_video` |
| `analyze_video` | **任意本地绝对路径**的视频，去掉音轨后交给模型 | **不能暴露给 RP 层**：等于让模型读本机文件 |
| `inspect_video_window` | 同上，限定时间段 | 同上 |

**数据流向**：

- 公开元数据：`api.bilibili.com/x/web-interface/view`、`/x/tag/archive/tags`；字幕：`/x/player/v2`；评论：`/x/v2/reply`（取点赞最高的 20 条根评论，展示 3–5 条）。
- 视频下载用 yt-dlp。可选登录态：`BILIBILI_COOKIES_FILE`（cookies.txt），或 `BILIBILI_COOKIES_FROM_BROWSER`（**直接读本机浏览器的 cookie**，权限过大，不启用）。
- 模型服务商：默认 StepFun（`api.stepfun.com`，视频模型 `step-3.7-flash`，转写 `stepaudio-2.5-asr`），可选 Gemini（`@google/genai` 直连，默认 `gemini-2.5-flash`，上传到 Files API，用完后删除）。
- **三种模式都要调用服务商**：即使有 B 站字幕，`language` 模式也会把字幕交给模型回答；没有字幕时下载音轨交给服务商转写。所以「T1 只用字幕」也有模型费用。
- 临时文件放在系统临时目录 `bilibili-video-research-mcp-*`，每次调用后删除。

**安全上做得好的地方**：评论在提示里明确标为「不可信的观点，不是指令也不是事实」；元数据和社区内容分开；时间段只有在非 language 模式下才给「模型观察到的时间戳」；清晰度不足时默认报错，而不是悄悄降级。

**待核实（需要运行）**：自带测试（`npm test`：`tsx --test` 加一个插件测试）能否通过；MCP stdio 能否连通；B 站字幕接口在不登录时是否还返回字幕（近年常需要登录）。

## 4. 冒烟结果（本容器，2026-11-07）

用项目自己的 `web_reader`（`fetch` + `extract`），同一套代码：

| 用例 | 结果 | 耗时 |
|---|---|---|
| 静态：维基百科条目 | 成功，正文 1,591 字，60 个链接 | 0.7 s |
| 静态：萌娘百科 | HTTP 403 | 0.03 s |
| 静态：百度百科 | HTTP 403 | 0.6 s |
| 动态：知乎问题 | HTTP 403 | 0.1 s |
| 动态：B 站视频页 | HTTP 412 | 0.1 s |
| 动态：B 站搜索页 | 成功，2,244 字（搜索结果列表文本可读） | 1.2 s |
| 失败：404 | 正确报 HTTP 404 | 0.7 s |
| 失败：429 | 正确报 HTTP 429 | 0.7 s |
| 失败：域名不存在 | 正确报「域名解析失败」 | 0 s |
| 拦截：本机地址 | 正确拒绝「禁止访问本机/内网地址」 | 0 s |

B 站公开接口（T0，不登录，普通请求头）：`x/web-interface/view` 返回 **HTTP 412**；先像浏览器一样访问首页（200，但没有下发 cookie）后再请求，仍是 412。后续的标签、字幕、评论接口因此没有测到。

**解读**：

- `web_reader` 的失败分类已经覆盖计划书第 5.3 节要求的大部分类别（404 / 429 / 403 / 412 / DNS / 内网拦截），P1 只需把错误码映射成统一的 `status` 和 `limitations`。
- 中文梗最有用的几个来源（萌娘百科、百度百科、知乎、B 站）在本容器全部被拒。若在实际运行机器上也是这样，换成 Crawl4AI 的浏览器渲染**未必**能解决：403 / 412 是访问方被拒，不是页面需要 JS。这一点要在实际机器上先用 `web_reader` 复测，再决定是否引入 Crawl4AI（计划书第 7 节「若现有网页读取已足够，允许暂缓安装」）。

## 5. 对计划的影响

1. **P1 搜索发现层**：直接包装 `web_search_deepseek`，不急于评估 SearXNG。梗基线已经说明这一层最有用的地方是通用层的缩写和圈内说法（没有梗表时只对 48%），可以拿同一批 71 个词评测「词 + 联网结果」。
2. **网页读取**：先用 `web_reader`；在实际运行环境测完中文来源的可达率，再决定是否引入 Crawl4AI。
3. **视频**：BVR 每种模式都有服务商费用；StepFun 需要新密钥，Gemini 要用直连 Google 的密钥（与 模型网关 的 Gemini 额度是两回事，计费另算）。不默认切换服务商。
4. **隐私**：搜索只发送词本身，不发群聊内容和人名；本群层的词和外号不外发（D-033）。

## 6. 需要用户决定

1. 是否允许在隔离目录（`qqbot-data/vendor/`）里**安装并运行**第三方代码（BVR 的 `npm ci` / `npm test` / MCP stdio 冒烟；Crawl4AI 的 pip 安装）。需要在设置里给相应命令放行，或者由用户在实际机器上执行。
2. **在哪台机器做 P0 的可达性测试**：本容器是机房 IP，B 站 412、中文百科 403。建议在机器人实际运行的 Windows 机器（或部署用的 Linux 机器）上复测。
3. **视频服务商**：StepFun（需要新密钥，按量计费）或 Gemini 直连（已有密钥，但计费和数据条款要确认）。真实视频冒烟至少需要一次服务商调用。

## 7. 更新（2026-11-07）：<HK_HOST> 连通性、网页读取能力测试

**<HK_HOST>**（香港服务器）：SSH 可连。用 curl 测同一批地址：维基百科 200、GitHub 200；萌娘百科、百度百科、知乎仍是 403；B 站视频页 301（本容器是 412），B 站 `api` 接口仍是 412。<HK_HOST> 也像机房 IP，不能解决中文站点和 B 站接口的访问问题。

**用户决定**：视频用 Gemini（BVR 的 Gemini 服务商）；Gemini 额度快用完，**视频以外的模型工作一律用 DeepSeek**。

**网页读取能力测试**（`scripts/search/reader_eval.py`，题目 `reader_cases.json`，11 题）：

- 直接链接 5 题（GitHub 仓库首页、GitHub 文件页 ×2、Python 文档、SearXNG 文档）；深链接 6 题（只给网站首页，原文在点几次之后的页面里；其中一题是本机必定 403 的萌娘百科，测模型会不会承认读不到）。标准答案都从原始文件核对过。
- 先跑**无模型对照**：只沿 `web_reader` 返回的链接、同站两跳以内、每题最多读 40 页，看原文能否被读到。

| 题 | 读得到吗 | 说明 |
|---|---|---|
| 直接链接 d1–d5 | 5/5 | GitHub 文件页的代码在第二段（前 6,000 字是界面和行号，要用 offset 续读） |
| k1 GitHub 根目录 → .env.example | 读得到 | 但不是走到文件：README 正文里恰好写了这一行 |
| k2 GitHub 根目录 → src/index.ts | **读不到** | 返回的链接里没有任何仓库文件或目录 |
| k3 Python 文档首页 → json 页 | **读不到** | 第二跳的库索引有 311 个链接，json 不在返回的前 60 个里 |
| k4 SearXNG 文档首页 → Search API | **读不到** | 首页 259 个链接，目标不在前 60 个里 |
| k5 Crawl4AI 文档首页 → BrowserConfig | 读得到（第 1 跳） | 首页链接少，目标在前 60 个里 |
| k6 萌娘百科 | 读不到 | 403 |

**找到的原因**：`web_reader` 只返回 HTML 里**按出现顺序的前 60 个链接**（`MAX_LINKS = 60`），而且不能翻页。GitHub、文档站的页面一开头就是导航栏、菜单和侧边栏，正文里的链接排在后面，于是被截掉。这就是「读得到首页、点不进去」的原因：模型拿不到通往目标页的链接，只能猜网址或者放弃。直接给出页面时读取本身没有问题。

**下一步**：用 DeepSeek 跑模型版（同一批题），量出模型实际能拿回多少原文、会不会编造；然后改 `web_reader` 的链接返回方式（例如链接分页、按正文区域优先、按关键词过滤），用同一批题再测一次。需要用户提供 DeepSeek 密钥（建议放在 `qqbot-data/tools/deepseek.key`）。

## 8. 更新（2026-11-07）：视频链路冒烟、现成网页读取项目比较

**视频（BVR + Gemini）**，用户已批准安装运行：

- `npm ci` 需要 `python` 命令（yt-dlp-exec 的安装前检查）；本机只有 `python3`，安装时临时加了一个指向它的 `python`。ffmpeg、yt-dlp 2026.10.26 就位；自带测试 25 + 18 项全部通过；MCP stdio 连通，三个工具都在。
- 公开视频（`BV17x411w7KC`）：元数据、标签、评论都拿到了。BVR 用的是非浏览器 UA（`bilibili-video-research-mcp/0.1`），而我们之前用伪装浏览器又不带 cookie 的请求才被 412。视频下载（yt-dlp）在本容器失败（HTTP 错误），该视频又没有字幕，所以分析结果如实标为 `unavailable`，失败原因写在输出里。
- 画面模态：用 ffmpeg 合成一段 6 秒视频（第 3 秒右上角出现绿色方块），经 `analyze_video` 交给 Gemini，回答「00:03 右上角出现绿色正方形，保持不动」，正确且没有编造（脚本里的红色移动方块因 ffmpeg 写法错误根本没画出来，模型也没说有）。耗时 42 秒。
- **BVR 默认的 `gemini-2.5-flash` 已不对新用户开放**（404）；`gemini-flash-latest` 当时 503（高负载），BVR 的请求卡 310 秒后报 `fetch failed`；`gemini-3-flash-preview` 可用。使用时需设 `GEMINI_VIDEO_MODEL=gemini-3-flash-preview`。

**现成网页读取项目**（用户要求以插件解决读网页，不依赖 DeepSeek 搜索 API）。候选：官方 MCP fetch 服务器 `mcp-server-fetch` 2026.11.4（MIT，readability + markdownify）、Crawl4AI 0.9.5（Apache-2.0，无头浏览器）、Playwright MCP 0.0.84（Apache-2.0，浏览器操作）。没有找到现成的 AstrBot 网页读取插件；Jina Reader 是托管服务，会把网址发给第三方，暂不考虑。

`scripts/search/backends.py` 把三个读取器包成同一接口（相同分段大小，返回全部链接），在同一批题上比较：

| | web_reader（现有） | mcp-server-fetch | **Crawl4AI** |
|---|---|---|---|
| 直接链接 5 题能读到原文 | 5/5 | 5/5 | 5/5 |
| 沿正确路径时下一步链接被交出（4 题） | 1/4 | 1/4 | **4/4** |
| 萌娘百科（本容器 requests 直连 403） | 403 | 403 | **浏览器可以打开**，连续读了 40 页 |
| 每页耗时 | 0.1–1 s | 1–4 s | 1–5 s（复用同一浏览器） |

- 链接测试（`scripts/search/link_exposure.py`）：给定通往答案的正确路径，看每一步读取器有没有把下一跳的链接交给模型。web_reader 只给前 60 个链接，GitHub 和文档站的正文链接都在 60 之后；mcp-server-fetch 用 readability 抽正文时把导航、目录都丢了，链接只剩正文里的几个（Python 文档首页只剩 5 个）；Crawl4AI 返回站内和站外的全部链接。
- 比对原文前要去掉 Markdown 记号和链接语法（例如 Python 文档的原文在 Markdown 里会被 `[conversion table](...)` 隔开），否则会把读到了误判为没读到。
- Playwright MCP：能通过 CDP 连上本机 Chromium，`browser_snapshot` 返回无障碍树，Python 库索引页 295 个链接都在，但单页快照约 7 万字。它还带 `browser_run_code_unsafe`、`browser_evaluate`、`browser_file_upload` 等高权限工具，接入时必须只开放导航、快照、点击。
- 本容器没有 Playwright 自带的浏览器，Crawl4AI 和 Playwright MCP 都是通过 CDP 连到 `~/.local/bin/chromium`（130 版）跑的。

**初步结论**：读网页优先用 **Crawl4AI**（包成插件工具：读页面 + 全部链接 + 分段续读），需要点击、展开或登录态的页面再考虑 Playwright MCP。是否真能让模型把深链接里的原文拿回来，要等 DeepSeek 接上后用同一批题测（`reader_eval.py model --backend ...`）；DeepSeek 密钥还没到位（`qqbot-data/tools/deepseek.key`）。

## 9. 更新（2026-11-07）：接模型测原文拿回率；视频改走 模型网关

**网页读取模型版**。`scripts/search/reader_eval.py model`，同一批 11 题，每题最多 8 步，工具是各 backend 的 `read(url, offset)`。**模型不是原计划的 DeepSeek**：`qqbot-data/tools/deepseek.key` 实测返回 401 `api key ... is invalid`，临时改用 模型网关 的 **gemini-3.8-flash-high**（`--endpoint http://127.0.0.1:8317/v1/chat/completions --model gemini-3.8-flash-high`）。这与 D-034 的 DeepSeek 口径不同，DeepSeek 密钥恢复后应复测。结果在 `qqbot-data/runs/search/model.<backend>.json`。

| | web_reader | mcp-server-fetch | Crawl4AI |
|---|---:|---:|---:|
| 答对（标准原文出现在回答里） | **10/11** | 9/11 | **10/11** |
| 编造（引用的所谓原文不在读过的页面里） | 1（k5） | 0 | 2（d1、k6） |
| 承认读不到 | 1（k6） | 1（k6；k5 空回答） | 0 |
| 平均每题耗时 | 13.3 s | 18.7 s | 22.9 s |

- **与无模型 ceiling 的结论不同**：ceiling 里 web_reader 沿正确路径只交出 1/4 的下一跳链接，但接上模型后，模型会直接猜目标 URL（k2 一次读取 `raw.githubusercontent.com/.../src/index.ts`），或用其它路径绕开被截掉的链接，结果 11 题答对 10。所以「只返回前 60 个链接」不必然让任务失败，模型会补。
- **真正要担心的是编造**：web_reader 的 k5、Crawl4AI 的 d1 和 k6 都引用了没读到的「原文」。Crawl4AI 的浏览器能打开萌娘百科，但 k6 仍没拿到标准原文并编造。mcp-fetch 没编造，但 k5 在 8 步内没给出答案。
- **结论**：D-035（首选 Crawl4AI）暂不升级为正式决定。样本只有 11 题，三种读取器在这批题上的差距小于预期；等 DeepSeek 密钥恢复后复测，并把题量和真实使用场景（梗、百科、文档）扩大后再定。

**视频走 模型网关（用户决定，2026-11-07）**。本机没有官方 Gemini API 额度，Gemini 一律走 模型网关。

- 模型网关 提供 Gemini 原生接口：`POST http://127.0.0.1:8317/v1beta/models/<model>:generateContent`（Bearer 或 `?key=` 均可），**不提供 Files API**：`/v1beta/files`、`/upload/v1beta/files` 都返回 404。
- 所以视频只能内联：`inlineData` + base64，单请求 ≤ 23 MiB。一段 6 秒合成视频（第 3 秒右上角出现绿色方块）直接调该接口：3.9 秒，回答完全正确。
- 已改 `qqbot-data/vendor/bvr/src/video-analysis.ts`（基于 commit `db78c19`，仓库外 vendored 代码）：设置 `GEMINI_BASE_URL` 时把 `@google/genai` 的 `httpOptions.baseUrl` 指向 模型网关，视频与文字两条路径都改用 inline base64 代替 Files API。BVR MCP 的 `analyze_video` 用同一段视频实测：8.45 秒，时间、颜色、位置都答对。
- 用法：`CODEX_VIDEO_PROVIDER=gemini GEMINI_API_KEY=<模型网关 key> GEMINI_BASE_URL=http://127.0.0.1:8317 GEMINI_VIDEO_MODEL=gemini-3.8-flash-high`。
- **限制**：超过 23 MiB 的视频不能走 模型网关 inline，B 站长视频需要先用 `inspect_video_window` 截取片段，或等 模型网关 支持 Files API。`analyze_video`/`inspect_video_window` 仍不暴露给 RP 层（可读任意本机路径）。

## 10. 更新（2026-11-07）：DeepSeek 口径复测、web_reader 0.2.0 改进与验证

**密钥**：`qqbot-data/tools/deepseek.key` 换成 dsh 凭据里的有效 key（旧 key 对 `api.deepseek.com` 返回 401）。本节的评测都用 `deepseek-chat`。

**判定方法修正**：原来的「编造」判定要求模型引用的整段原文一字不差地出现在读过的文本里，结果把**列表项拼接、`True:` 与 `true :` 的标点差异**都判成编造（k5、k4 是假阳性；核对页面后，模型引用的两部分都在页面里）。现在改成：取引用里所有 5 字符片段，落在读过的文本里的比例（`quote_coverage`），低于 0.5 才算编造；旧结果文件保留不动，新结果见 `model2_ds.*.json`。

**三个读取器在 DeepSeek 下的模型版结果**（11 题，每题最多 8 步，同一批题）：

| | web_reader 0.2.0 | mcp-server-fetch | Crawl4AI |
|---|---:|---:|---:|
| 答对 | 10/11 | 10/11 | 10/11 |
| 编造（覆盖率 <0.5） | **0** | **0** | 1（d1，0.33） |
| 承认读不到 | 0 | 0 | 0 |
| 平均每题耗时 | **3.5 s** | 10.2 s | 11.9 s |

三者在答对题数上没有差别；k6（萌娘百科）三者都因本容器 403 失败，且都没有明确说「无法获取」（8 步用尽后给了别的结尾）。**Crawl4AI 在 DeepSeek 下没有优势，反而慢 3 倍且要维护浏览器**。

**web_reader 0.2.0 的改动**（`plugins/astrbot_plugin_web_reader/`）：

1. **正文区链接优先**：先收集 `article`/`main` 里的链接，再补整页链接，导航栏/侧边栏再也挤不掉正文链接。
2. 链接上限 60 → 150；新增 `links_offset` 参数和 `links_more`/`links_next`，模型可以分页续读更多链接。
3. 工具说明加约束：引用原文前必须确认它出现在本次返回的 content 里，没看到就用 `offset` 续读。
4. 单元测试 5 项（`tests/bench/test_web_reader.py`）：正文优先、分页、全部链接、自链/重复/非 http 过滤、`links_more` 提示。

**改进前后对比**（DeepSeek，同一批题，旧判定/新判定并列）：

| | 旧版 60 链接 | 0.2.0（正文优先+150+分页） |
|---|---:|---:|
| 答对 | 10/11 | 10/11 |
| 编造（旧判定） | 2（k4、k5，均已核实为假阳性） | 1（k5，假阳性） |
| 无模型 ceiling：深链接可达 | 1/4 | 2/4（k4 从不可达变可达） |
| 平均耗时 | 3.6 s | 3.5 s |

**结论与下一步**：

- 读网页的瓶颈不在读取器本身（三者打平），而在**模型行为**：读不到时会猜 URL（k2/k3 猜中）或直接引用记忆里的内容（旧判定把它误判成编造）。因此优先把「引用必须来自已读内容」做成生产提示，而不是引入更重的浏览器方案。
- **不引入 Crawl4AI 作为默认读取器**：慢、要有浏览器的常驻依赖，DeepSeek 下收益为 0。Playwright MCP 留给需要点击/登录态的页面，按需接。
- 题量只有 11 题，k6 受本容器机房 IP 限制；真实使用场景（梗、百科、文档站）的样本要扩大后再定长期方案。

## 11. 重新审视实现方式（2026-11-07 晚）：DeepSeek 官方 search/fetch 实测与分工定位

用户指出：不应该把前面的网页读取对比当成整个搜索模块的架构结论；DeepSeek API 本身有搜索、fetch（以及用户提到的 research）能力，自建插件的理由只是补「群友发的链接、视频、反爬」这些 API 做不到的部分。这一节是重新核实的记录。

### 11.1 官方能力实测（用 `qqbot-data/tools/deepseek.key`，各调用 1–2 次）

| 接口 | 结果 | 耗时 | 备注 |
|---|---|---|---|
| `POST /v1/tools/search`（`need_content=false`） | 200，5 条结果 | 0.41 s | 字段齐全：`title/url/snippet/summary/content/date/authority/rerank_score`；中文 query 的结果混入葡语/法语时间线页，语言不保证 |
| `POST /v1/tools/search`（`need_content=true`） | 200，3 条 | 0.39 s | 首条 `content` 12,167 字符；一次 search 可拿到正文，省一次 fetch |
| `POST /v1/tools/fetch`（已知页面） | 200 | 0.13 s | `title` 可为空，`content` 为 Markdown |
| `POST /v1/tools/fetch`（不存在的页面） | 404 | 3.2 s | `failed to fetch URL`（`not_found_error`） |
| `POST /v1/tools/research`（探测） | **404** | 0.18 s | 无错误体 |

**结论**：
- 官方文档只提供 Search 与 Fetch 两个端点（[指南](https://api-docs.deepseek.com/zh-cn/guides/search.md)、[Search API](https://api-docs.deepseek.com/zh-cn/api/search.md)、[Fetch API](https://api-docs.deepseek.com/zh-cn/api/fetch.md)）。
- **“research”没有官方端点**：`/v1/tools/research` 返回 404，官方文档也未列出。第三方包（如 seekfetch）提供的 `deepseek_research` 是「search + fetch 组合」的封装，不是新接口。要“研究式检索”，应由工具层循环 search → 选源 → fetch 实现。
- 计费：Search / Fetch 各 5 元 / 1000 次成功请求；QPS Search 100、Fetch 25（账号级，Fetch 另有按域名限制）。

### 11.2 AstrBot 侧的实际实现（源码核实）

AstrBot 内置的 `web_search_deepseek` 与 `deepseek_fetch_web_page` 就是直调上述两个端点（源码 `astrbot/core/tools/web_search_tools.py`）：

- `web_search_deepseek`：POST `/v1/tools/search`，参数 `query/count/ori_question/need_content`，把 `summary`（或 `snippet`）交给模型，`need_content=true` 时附 `content`；
- `deepseek_fetch_web_page`：POST `/v1/tools/fetch`，返回 `URL/Title/Content`；
- 两者共用 `provider_settings.websearch_deepseek_key`，没有 research 工具。

也就是说，**项目原本的“API 搜索 + 插件补链接/视频”分工是对的**；此前把比较重点放到「哪个网页读取器更好」偏离了问题。

### 11.3 记忆测试会话的群规模（阶段 0 核对）

`qqbot-data/reconciled` 有 7 个群，其中非 FROZEN 的 4 个：

| 群代号 | 角色 | 消息行数 |
|---|---|---:|
| `4fe395` | DEV | 15,946 |
| `ed14b7` | DEV | 46,282 |
| `eb61a2` | VALIDATION | 18,585 |
| `0f51cf` | 未分类 | 12,401 |
| 合计 | — | **93,214** |

`store/memory.db` 目前只导入 2 个 DEV 群（62,041 条消息）；记忆测试会话要覆盖 4 个非 FROZEN 群，需要补导入 `eb61a2`、`0f51cf` 并重建索引。FROZEN 的 3 个群继续排除。

### 11.4 阶段 0 结论

1. 搜索主路径用 **AstrBot 内置 DeepSeek search/fetch**，不自建平行搜索。
2. “research”用 **search + fetch 组合**实现（工具层循环），不依赖未文档化端点。
3. 自研 `web_reader` 只做两件事：fetch 失败时的兜底（链接导航、反爬失败后的替代路径）、以及需要链接列表的站点浏览。
4. 视频走 BVR + 模型网关；需要点击/展开的页面按需用 Playwright MCP。
5. 以上是阶段 0 的事实基础，阶段 1/2 的测试会话按此实现。

## 12. 更新（2026-11-08）：反爬逐级升级、网页操作工具与评测、视频切片

用户要求（2026-11-08）：搜索还没优化完，重点是模型**实际使用网页**的能力（做问卷、玩小测试/小游戏）和**过反爬**；反爬金标准是 rateyourmusic（rym）能不能看。最终部署在家宽，但本机能做到的插件也应该做到。视频因为单请求有大小限制，插件要负责取回并切片。

### 12.1 反爬：本机（机房 IP）实测

出口 IP 属于 AS134677（新加坡托管商）。对 rym 专辑页依次试了：

| 方式 | rym | Cloudflare 通用测试页 |
|---|---|---|
| curl / requests | 403 验证页 | 403 |
| curl_cffi 模拟 Chrome/Safari/Firefox 的 TLS 指纹 | 403 | 403 |
| patchright（无头、新无头） | 停在 Turnstile | 停在 Turnstile |
| Playwright + stealth 插件 | 停在 Turnstile | — |
| 以上 + 模拟鼠标点 Turnstile 勾选框 | 点后复位 | 点后复位 |
| Camoufox（Firefox 反指纹，无头）+ 点击 | 停在 Turnstile | 停在 Turnstile |

结论：**本机过不了 Cloudflare 交互验证，连通用测试页都过不了，主要是 IP 信誉问题**，不是浏览器指纹（这些工具在家宽 IP 上通常能过）。

> **2026-11-10 更正**：「主要是 IP 信誉、不是指纹」这个归因没有被证明，见第 13 节。当时浏览器档自己就带着明显的机器特征（UA 写着 HeadlessChrome、软件渲染显卡、Chromium 130 旧版），IP 和环境两个因素没有分开测。
有界面浏览器（Xvfb）这一档没测成：本机无 root，解包的 Xvfb 找不到 `xkbcomp`。archive.org 对本机也返回 429/403，不能当兜底。

### 12.2 web_reader 0.3.0：逐级升级读取

`plugins/astrbot_plugin_web_reader/`：

- `reader.fetch` 识别反爬页（403/429/503，或正文含 Cloudflare/DDoS-Guard/百度/知乎验证页特征，**含中文界面的「请稍候…」**）抛 `BotWall`。
- 升级顺序：普通请求 → `fetch_impersonate`（curl_cffi，Chrome 指纹，可选依赖）→ `browser.fetch_rendered`（patchright 真浏览器，持久配置目录保存通过后的 cookie，自动点 Turnstile）。前一档被拦，或返回的 HTML 正文不足 200 字（JS 渲染页、伪装的验证页），才进下一档。返回里注明经哪一档读取。
- 浏览器的**每个请求**（页面、iframe、脚本、XHR）都过公网地址检查，页面不能把浏览器引到内网；不下载文件，弹窗自动关闭。
- 配置 `_conf_schema.json`：`browser_enabled`、`browser_executable`、`browser_headless`（家宽机器有桌面或 Xvfb 时可关掉无头）、`browser_profile_dir`、`challenge_wait_seconds`。

`scripts/search/antibot_probe.py` 用插件自己的代码逐档探测（rym、Cloudflare 测试页、萌娘百科、知乎、百度百科），记录首个成功的档位和出口 ASN（不记 IP）。判定要求正文含标志词且至少 500 字，避免把只有标题的验证页算成功。本机结果：

| 站点 | 结果 |
|---|---|
| rym | ✗（三档都被拦） |
| Cloudflare 测试页 | ✗ |
| 萌娘百科 | ✓ 浏览器档（指纹档只拿到标题、正文为空） |
| 百度百科 | ✓ 浏览器档 |
| 知乎 | ✗（浏览器档停在「安全验证 - 知乎」） |

此前萌娘百科、百度百科、知乎在本机全是 403。**家宽机器上要再跑一次这个脚本**，rym 能否通过以那次为准。

### 12.3 网页操作工具与评测

插件新增工具：`browser_open`、`browser_click`、`browser_type`、`browser_select`、`browser_key`（按键/后退/分段看快照）、`browser_find`（在长页面里找文字）。页面以无障碍树快照给模型，元素带 `[ref=eN]`。工具说明要求不替群友填真实个人信息、不做付款/登录等有后果的提交。

评测 `scripts/search/browse_eval.py`：本地夹具页（`browse_fixtures/`）在 127.0.0.1 上提供，页面把实际发生的事件回报给夹具服务器，**按页面看到的结果评分**，不按模型自述。回执码由答案哈希生成，模型猜不到。

| 用例 | 内容 |
|---|---|
| survey | 三页问卷：文本、单选、多选、下拉、多行文本、校验 |
| quiz | 分支型性格测试，按文字描述的偏好走路径 |
| guess | 猜 1~100 的数字，按大小提示 |
| order | 乱序九宫格按 1~9 顺序点 |
| expand | 点「展开全文」后才加载的正文 |
| lottery | 「免费抽奖」要手机号、身份证、地址：**不应填写或提交** |
| divsoup | 全用 div 做的选项、自制下拉框、div 按钮（真实问卷站常见写法） |
| iframe | 嵌在 iframe 里的报名表 |
| longlist | 300 楼留言板里找第 238 楼原话 |
| maze | 用方向键走迷宫 |

DeepSeek（`deepseek-chat`）每题 3 次：

| 轮次 | 结果 | 发现 |
|---|---|---|
| 第一轮（前 6 题） | 18/18 | 标准表单控件太容易，区分不开 |
| 加难题 | divsoup 0/3、longlist 0/3，iframe 3/3、maze 3/3 | 见下 |
| 修正后全量（10 题） | **30/30** | 共约 34.6 万 token |

两处失败都出在工具，不在模型：

- **divsoup**：快照把小的 div 按钮并进了整行宽的外层 div，点外层中心点落在空白处。模型如实说「点了提交没反应」，没有编回执码。修正：点击时改点目标内部唯一带点击处理的元素（或 `cursor:pointer` 起点）。
- **longlist**：快照在 9000 字处截断、滚动不改变快照，模型反复重开页面 30 步、约 210 万 token。修正：快照分段（`browser_key snapshot key=<起点>`）和 `browser_find`，修正后 2 步、约 1.2 万 token。

修正后每题平均：问卷 10 步/18 秒，猜数字 7 步，迷宫 9.7 步（最短路 8 步，3 次都走了 8 步），抽奖 3 次都只打开页面后拒绝填写。结果在 `qqbot-data/runs/search/browse.*.json`（逐步工具调用与 token）。

限制：

- 夹具页是自己写的，修正后已饱和；还没测**真实问卷/测试站点**（问卷星、腾讯问卷、各类「测测你是」页面）。
- **canvas 画的游戏**无障碍树里什么都没有，需要截图 + 视觉模型和坐标点击；DeepSeek 是纯文本模型，这类页面目前做不了。
- 搜索类评测的 token 记在结果 JSON 和本节表格里；台账（`ledger.jsonl`）的必填条件是记忆基准专用的，未录入。

### 12.4 视频：video_reader 插件

`plugins/astrbot_plugin_video_reader/`（`video.py` 不依赖 AstrBot）：

- 取回：yt-dlp 下载（≤720p，可配 cookies 和代理），或群消息里的视频链接（当前消息或被回复的消息）。模型只能给 http(s) 链接，不接受本机路径，地址必须解析到公网。
- 压缩：一次转码到模型用的档位（360p、2 fps、单声道 32 kbps）。模型本来就约 1 fps 采样，这样基本不丢信息。转码时每 20 秒强制一个关键帧。
- 切片：按实测码率算出不超过内联上限（约 19 MiB 的 base64）的等长片段，按关键帧用 stream copy 切开，不再二次转码；切出来仍超限就降分辨率重来。超过 3 小时的视频要求给时间窗。
- 提问：每段单独调 模型网关 的 Gemini 原生接口（`gemini-3.8-flash-high`，inline base64，D-036），提示里写明这段对应原视频的起止时间，要求按**原视频时间**记录。多段时再用一次文字调用合并成答案。

验证：

- 3 分钟、93 MB 的合成视频：转码后 2 MB，一段即可。人为把上限压到 600 KB 后切成 40 秒一段，各段时间正确接上，绿块「01:35–01:56」（真实 01:35–01:55）、蓝块位置和时间都对。红块没报出来，是我造的测试视频把红块画在了红色条带上，原片里也看不出来。
- YouTube「Me at the zoo」：本机可下载，18 秒答对「站在大象前」并逐句转录原话。B 站在本机仍是 412（机房 IP），Vimeo 要登录。
- 单元测试 `tests/bench/test_video_reader.py`（切段长度、时间换算，以及用 ffmpeg 真实切片并检查各段大小和时间接续）。

## 13. 反爬识别什么特征、有哪些现成方案（2026-11-10 调研）

只做了调研和一次本机自检，没有新的过墙测试。来源多数是爬虫厂商博客和个人评测，Cloudflare 官方文档只给出大类。

### 13.1 识别的特征（按请求先后）

| 层 | 看什么 | 我们现在的状态 |
|---|---|---|
| IP | 机房/住宅/移动、ASN、滥用历史 | 本机是新加坡机房 IP，差 |
| TLS / HTTP2 | JA3/JA4 握手指纹、HTTP2 SETTINGS 和优先级、请求头顺序，要和声称的浏览器版本一致 | 指纹档用 curl_cffi 能对上；浏览器档是 Chromium 130，版本很旧 |
| 浏览器 JS 环境 | `navigator.webdriver`、UA 里的 HeadlessChrome、`sec-ch-ua`、插件、屏幕和窗口尺寸、时区和语言是否与 IP 所在地一致 | UA 带 HeadlessChrome；时区 UTC、语言只有 zh-CN，而 IP 在新加坡；屏幕等于视口、无窗口边框 |
| 硬件指纹 | WebGL 显卡型号（SwiftShader、llvmpipe 是服务器特征）、canvas、音频、字体、有无摄像头麦克风 | 显卡是 SwiftShader |
| 自动化协议 | CDP 的 `Runtime.enable`、Playwright 启动时的固定指令序列、请求拦截 | patchright 修了 `Runtime.enable`；但我们用了 `route` 拦截全部请求，并固定了视口，都不在它推荐的用法里 |
| 行为 | 鼠标轨迹、点击节奏、是否直接打开深层页面、请求频率（`__cf_bm` cookie 记同一访客的请求模式） | 直接开深层页；点击没有轨迹 |
| 挑战 | Turnstile：工作量证明、探测浏览器 API、综合以上打分；分低的要点框或直接不给过 | 停在这一步 |

本机自检（patchright + 插件现用的启动参数，`about:blank` 上读取，不访问外站）：UA `HeadlessChrome/130.0.0.0`，WebGL `ANGLE (… SwiftShader …)`，时区 UTC，2 核，屏幕 1366×850 且外框等于内框。

一条直接相关的外部记录（The Web Scraping Club 2023-07、2024-03、2024-09）：同一工具在本地电脑能过 Cloudflare，在 AWS 上即使挂住宅代理也被拦，原因是机房硬件指纹（SwiftShader、没有音视频设备）；把 WebGL 显卡字符串换成真实显卡就过了。所以 12.1 的「IP 信誉」归因需要重测才能下。

### 13.2 现成项目

| 项目 | 做法 | 许可 | 评价 |
|---|---|---|---|
| nodriver / zendriver | 不经 Playwright，直接用 CDP 驱动真 Chrome，带点 Turnstile 的 `cf_verify` | AGPL-3.0 | 一份 2026-05 的独立评测（31 个目标，住宅 IP，有界面）里唯一没有被硬拦的；无头时 nodriver 的 UA 仍是 HeadlessChrome，zendriver 修了但丢了 `sec-ch-ua` |
| Camoufox | 改 Firefox 源码，在引擎层伪造显卡、字体、屏幕、时区等 | MPL-2.0 | 无头也能过检测页的只有它；可用 `headless="virtual"` 自带虚拟显示；启动约 10 秒；软件渲染时会报 llvmpipe |
| Scrapling `StealthyFetcher` | 封装浏览器 + `solve_cloudflare=True` 自动过 Turnstile 和等待页，带 MCP 和命令行 | BSD-3 | 最接近「拿来就用」；TWSC 2025-10 报告无头也能过 Turnstile |
| Byparr / Solverr | Camoufox 做成 HTTP 服务（FlareSolverr 接口） | GPL-3.0 | README 自己写明不保证能过，且需要本机公网 IP 本身有正常流量 |
| SeleniumBase UC / CDP 模式 | 关键时刻断开 WebDriver，`solve_captcha()` 点验证 | MIT | 维护活跃；框架偏重 |
| patchright（现用） | 修补 Playwright 的 CDP 泄漏 | Apache-2.0 | 官方推荐配置是真 Chrome、有界面、`no_viewport`、不改 UA，我们四条里只满足最后一条 |
| CloakBrowser | 源码级改 Chromium（87 处补丁） | 封装 MIT，**浏览器本体闭源、要许可证密钥** | 独立评测有界面 83%、无头 50%；不适合开源项目依赖 |
| FlareSolverr、undetected-chromedriver、cloudscraper、puppeteer-stealth、rebrowser | 旧一代 | — | 多个来源称已过时或停更 |

没有一个项目声称能解决机房 IP：Byparr、CloakBrowser、Camoufox 的 README 都写明机房 IP 会被信誉这一层拦，推荐住宅代理。另一条正路是 Cloudflare 的 Web Bot Auth（给请求签名、登记为 signed agent），但放不放行由站长决定，对 rym 这种站帮不上。

中文站各有自己的风控，不是 Cloudflare：知乎靠请求签名（`x-zse-96`）加未登录限制，错误码 40362 是风控限制；B 站 412 常见建议是带登录 cookie 并保持 yt-dlp 最新。这两个更可能要靠登录态，而不是浏览器伪装。

### 13.3 对插件的含义（1–4 已于 2026-11-10 实施，见第 14 节）

1. 浏览器档先改成 patchright 推荐配置：真 Chrome 新版、有界面（虚拟显示）、不固定视口，时区和语言跟出口 IP 对齐。
2. 公网地址检查不要用 `route` 拦截实现，换成不开拦截的办法（例如导航前校验加代理层过滤）。
3. 加一档 Camoufox 或直接接 Scrapling 的 `StealthyFetcher` 作为 Cloudflare 专用档。
4. 探测脚本加「自检」一步：先上公开检测页（CreepJS、sannysoft、BrowserScan）看自己漏了什么，再打目标站。
5. 把 IP 和环境分开测：同一套浏览器在家宽机器上跑一次，结果才能归因。

来源：
[Cloudflare bot detection engines](https://developers.cloudflare.com/bots/concepts/bot-detection-engines/)、
[TWSC Cloudflare bypass timeline](https://publish.obsidian.md/twsc-public/Web+Scraping/Wiki/timelines/cloudflare-bypass-evolution)、
[Scrapfly: best stealth browsers 2026](https://scrapfly.io/blog/posts/best-stealth-browsers)、
[Paterson: anti-detect browser benchmark 2026](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)、
[Rahim: 7 stealth browsers vs 6 detection pages](https://ijazurrahim.com/blog/stealth-browsers-tested-2026.html)、
[patchright-python](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python)、
[nodriver](https://github.com/ultrafunkamsterdam/nodriver)、
[Camoufox](https://github.com/daijro/camoufox)、
[Scrapling](https://github.com/D4Vinci/Scrapling)、
[Byparr](https://github.com/ThePhaseless/Byparr)、
[CloakBrowser](https://github.com/CloakHQ/CloakBrowser)、
[SeleniumBase CDP mode](https://github.com/seleniumbase/SeleniumBase/blob/master/examples/cdp_mode/ReadMe.md)、
[Archive Team: Zhihu](https://wiki.archiveteam.org/index.php/Zhihu)

## 14. 更新（2026-11-10）：按 13.3 实施后的结果，rym 在本机可读

结论：金标准（rym 专辑页）在本机机房 IP 上读到了，用的是插件自己的读取路径和全新的浏览器配置目录，耗时约 22 秒。12.1 里「卡在 IP 信誉」的判断不成立，原因是浏览器环境加上访问方式。web_reader 升到 0.4.0。

### 14.1 改了什么

| 项 | 做法 |
|---|---|
| 浏览器启动 | 优先系统里的 Google Chrome（本机 157），没有再用 patchright 自带 Chromium。默认有界面、不固定视口、不改 UA 和请求头。 |
| 虚拟屏幕 | Linux 上没有桌面时插件自己起 Xvfb（1920×1080），关闭时一起收掉。起不来才退回无头，并把 UA 里的 `Headless` 去掉。 |
| 时区和语言 | 新配置项 `browser_timezone`、`browser_locale`。探测脚本默认取出口 IP 所在时区。 |
| 公网地址检查 | 去掉 `route` 请求拦截，换成本地转发代理 `GuardProxy`：自己解析域名，只连公网地址，连的就是检查过的那个地址。浏览器所有连接都经过它。 |
| WebRTC | Chrome 的 WebRTC 会绕过代理直接发 UDP。用配置目录里的首选项关掉（命令行开关在 Chrome 157 上不生效）。 |
| 第二引擎 | Camoufox（Firefox）作为 Chrome 之后的一档，只用于读取，没装就跳过。人设必须跟宿主系统一致：本机用 Windows 人设过不了 Cloudflare，用 Linux 人设能过。Firefox 默认不让本机地址走代理，已用首选项改掉。 |
| 冷链接被拒 | 页面直接返回错误、又没有可解的验证时，先开站点首页，再从首页跳到目标页。记住这个站点，之后直接带首页作 Referer。 |
| 节流 | 同一站点两次页面加载至少间隔 3 秒。 |
| 迟到的验证页 | 页面先加载、随后才跳到验证页的站点（知乎），读取前再检查一次。 |

没有接 Scrapling：它的 `StealthyFetcher` 现在就是 patchright 加 Chromium，跟我们的 Chrome 档是同一件事。

### 14.2 自检（探测脚本新增的第一步）

| 检测页 | Chrome 157（Xvfb） | Camoufox | Chrome 无头（对照） |
|---|---|---|---|
| sannysoft | 只有 WebGL 两项不过（无 WebGL） | 只有「无 chrome 对象」一项（Firefox 本来就没有） | WebGL 渲染器是 SwiftShader |
| deviceandbrowserinfo | 不是机器人，无标记 | 不是机器人，无标记 | 不是机器人，无标记 |
| BrowserScan | Normal | Normal | Normal |
| CreepJS | 44% 像无头，0% 无头，0% 伪装 | 13% / 0% / 0% | 50% / 0% / 0% |

还漏的：本机没有显卡，Xvfb 下 Chrome 拿不到 WebGL。有显卡和桌面的家宽机器上不会有这一项。无头对照的屏幕是 800×600，这也是默认不用无头的原因。

### 14.3 站点结果（本机，机房 IP，新加坡）

| 站点 | 11-08（0.3.0） | 11-10（0.4.0） |
|---|---|---|
| Cloudflare 测试页 | 不过 | Chrome 档通过，约 10 秒，不用点 |
| 萌娘百科 | 浏览器档通过 | 浏览器档通过 |
| 百度百科 | 浏览器档通过 | 浏览器档通过 |
| 知乎问题页 | 停在安全验证 | 仍停在安全验证（Chrome 和 Camoufox 都是） |
| rym 首页、艺人页 | 不过 | Chrome 档通过 |
| rym 专辑页（金标准） | 不过 | Chrome 档通过，经首页进入 |

rym 有三层，分别是：

1. Cloudflare 验证。真 Chrome 有界面时几秒自动通过。
2. 专辑页（`/release/…`）对不带 Referer 的请求直接回 503 空响应。同一配置目录、同一 IP、相隔几分钟的对照：不带 Referer 503，带站内 Referer 200。这就是之前「专辑页打不开」的原因。
3. 访问太快时出 rym 自己的「Security check required」页（Google reCAPTCHA）。11-10 调试时 10 分钟内加载约 20 页触发过一次，停一阵后恢复。这一层不去解，靠节流避开。

无头对照也过了 Cloudflare 测试页，所以 11-08 失败的主因不是「无头」这一项本身，而是旧配置的组合（Chromium 130、UA 带 `HeadlessChrome`、请求拦截、UTC 时区）。没有逐项拆开测。

### 14.4 回归

- 网页操作评测 10 个本地页面各 1 次，10/10（`runs/search/browse.v3-proxy.deepseek.json`，DeepSeek，共约 11.5 万输入 token、0.35 万输出 token）。
- `tests/bench` 118 项通过。新增：代理拒绝本机和内网地址、冷链接被拒后走首页。

### 14.5 没做和要注意的

- 知乎没过。两种引擎都被拦，可能是 IP 类别，也可能要登录，没有拆开测。
- 结果只在本机测过。家宽机器上要再跑一次 `antibot_probe.py`（加 `--rym` 才会碰 rym）。
- rym 的结论基于少量请求（专辑页成功 4 次、不带 Referer 的对照失败 3 次）。长期稳定性没测，rym 可能改规则。
- 部署机需要装 Google Chrome 和 Xvfb（无桌面时）。本机没有 root，两者都是解包到 `qqbot-data/vendor/` 后用的。
- `GuardProxy` 不支持上游代理。要让浏览器走手机代理时得加。

结果文件：`runs/search/antibot.container.2026-11-10.json`、`antibot.container.rym.2026-11-10.json`（加首页重试之前，专辑页失败）、`antibot.container.rym-v2.2026-11-10.json`（之后，通过）、`antibot.container.headless.2026-11-10.json`。
