# 表情包数据集（只收集，不发送）

> 目标：把群聊/手动上传的表情包整理成可标注、可评测、可复用的数据集，改善 AI 对表情包的理解。
> **不包含发送能力**：采集插件不注册任何发送工具，也不装 stealer 等能发表情包的插件。
> 决策：`DECISIONS.md` D-018。

## 1. 目录与格式

```
data/sticker_dataset/
├─ inbox/            # 自动采集的候选原图（未标注）
├─ images/           # 标注成功/审核后的图片
├─ rejected/         # 不是表情包或违规的图片
├─ inbox_meta.jsonl  # 采集元数据（来源、信号、哈希）
├─ labels.jsonl      # 标注结果（一行一张）
├─ review.csv        # 人工复核导出（report 生成）
└─ stats.json        # 统计
```

`labels.jsonl` 关键字段：

```json
{
  "id": "sha256",
  "file": "images/<sha>.gif",
  "source": "group|private|manual",
  "umo_hash": "会话哈希",
  "sender_hash": "发送者哈希",
  "signals": {"sub_type": 1, "summary": "[动画表情]"},
  "caption": "画面描述",
  "labels": {
    "emotion": ["无语", "嫌弃"],
    "intent": "吐槽/不想理",
    "text": "图中文字",
    "character": "角色/来源",
    "usage": ["接梗", "被问烦了回一张"],
    "nsfw": false
  },
  "confidence": 0.8,
  "reviewed": false,
  "notes": ""
}
```

- 隐私：只存 `umo_hash`/`sender_hash`，不存原始 QQ 号；**不提交 git、不公开**。
- 去重：`sha256`；近重复后续可用 dHash 扩展。

## 2. 采集（插件）

`plugins/astrbot_plugin_sticker_collector`（已安装到 `data/plugins/`）：

- 监听所有消息，从 **raw OneBot 段** 读取 `sub_type/summary` 判断是否表情包；
- 只收「候选」：`sub_type==1`、summary 含「动画表情」、GIF 等；普通照片默认不收；
- 手动入口（管理员）：引用一张图发 `/sticker add`；
- `/sticker status` 查看数量/占用；
- **不发送消息、不注册 LLM 工具**。

已知限制：少数商城表情以 `mface` 上报时会被 AstrBot 适配器跳过，采集器看不到。

## 3. 标注

```powershell
# 自动标注（gemini-3.8-flash），默认每次 10 张
python scripts\label_sticker_dataset.py --limit 20
# 只看结果不落盘
python scripts\label_sticker_dataset.py --dry-run
```

taxonomy（初始）：开心 / 无语 / 生气 / 惊讶 / 嘲笑 / 委屈 / 得意 / 疑惑 / 哭 / 摆烂 / 害怕 / 尴尬 / 敷衍 / 其他。
`intent` 为短句（吐槽/安慰/拒绝/接梗/嘲讽…）。

```powershell
# 统计 + 导出人工复核 CSV
python scripts\sticker_dataset_report.py --review-csv
```

人工复核建议：改 `review.csv` 的 `emotions/intent/text/nsfw/reviewed/notes` 后手工同步回 `labels.jsonl`（或后续加合并脚本）；标注错误的图移到 `rejected/`。

## 4. 评测

```powershell
python scripts\eval_sticker_understanding.py --limit 10
```

对比两种 prompt：通用「描述图片」 vs 表情包感知「画面+文字+情绪+场景」，输出
`emotion_overlap` 与 `intent_jaccard`，用于衡量 caption prompt / 检索改进是否有效。

## 5. 用它改善理解（不发送）

1. 把 AstrBot 的 `image_caption_prompt` 改为表情包感知（bootstrap 已改）：群聊图片会得到"画面+文字+情绪/场景"；
2. 人设：看到表情包先理解情绪/梗，用自然反应回应，不逐字描述；**不主动发表情包**；
3. 第二阶段（可选）：对已标注库做 dHash 近似匹配，命中时把标签注入上下文，让模型对重发的表情包理解更准；
4. 数据集可继续用于评测、few-shot、未来微调/检索（微调暂不做）。

## 6. 运维

- 备份：`data/` 已包含数据集，`scripts/backup_data.py` 会一起打包；
- 清理：删除 `inbox/` 中误收图片即可；`/sticker status` 看占用；
- 迁移 VPS：`data/sticker_dataset/` 随 `data/` 搬。
