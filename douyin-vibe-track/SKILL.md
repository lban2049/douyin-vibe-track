---
name: douyin-vibe-track
description: 监控已配置的抖音/TikTok、视频号、快手账号近期作品，确认并维护监控账号 ID，获取 TikHub 用户资料和主页作品数据，下载高热视频，并生成每日 PPT 报告。当用户要求添加、删除、查看或执行这些平台的账号监控，创建每日视频报告，或管理此流程的 TikHub API Key 时使用。
---

# Multi-Platform Vibe Track

使用此 skill 管理本地监控工作目录，并对已配置的抖音/TikTok、视频号、快手账号执行一次每日扫描。外部定时框架负责每天调用此 skill；此 skill 只处理单次执行。

## 工作目录

默认使用 `~/douyin-vibe-track` 作为工作目录。执行任何操作前，先确保以下路径存在：

```text
~/douyin-vibe-track/
+-- config.json
+-- accounts.json
+-- state.json
+-- reports/
```

如果文件缺失，使用以下默认内容创建：

```json
{
  "tikhub_api_key": "",
  "timezone": "Asia/Shanghai",
  "lookback_hours": 72,
  "request_timeout_seconds": 30,
  "download_timeout_seconds": 120,
  "max_retries": 3,
  "page_count": 20,
  "sort_type": 0,
  "reports_dir": "",
  "thresholds": {
    "douyin": { "like_count": 10000 },
    "wechat_channels": { "like_count": 10000 },
    "kuaishou": { "like_count": 10000 }
  },
  "platforms": {
    "wechat_channels": { "enabled": true },
    "kuaishou": { "enabled": true }
  },
  "wechat_channels": {
    "decrypt_mode": "builtin",
    "keep_encrypted_copy": false
  }
}
```

```json
{
  "accounts": []
}
```

```json
{
  "last_run_at": null,
  "reported_post_keys": []
}
```

旧版 `like_threshold`、`reported_aweme_ids` 和抖音平铺账号字段仍可读取。脚本首次运行时会原地迁移并补写新字段。

不要把 TikHub API Key 存入 skill 目录或仓库。

## 报告目录

从 `~/douyin-vibe-track/config.json` 读取 `reports_dir`。如果缺省或为空字符串，报告默认写入工作目录下的 `reports/`。

## API Key

从 `~/douyin-vibe-track/config.json` 读取 `tikhub_api_key`。

- 如果缺少 key，且用户已在当前对话中提供，写入 `config.json`。
- 如果缺少 key，且用户没有提供，在调用脚本前向用户索要 TikHub API Key。
- 不要让脚本提示用户输入 key。Agent 必须先完成 key 配置。

## 账号管理

账号统一按以下结构保存：

```json
{
  "accounts": [
    {
      "platform": "douyin",
      "display_name": "TikTok",
      "homepage_url": "https://www.douyin.com/user/MS4w...",
      "identity": {
        "sec_user_id": "MS4w...",
        "user_id": "107955",
        "unique_id": "tiktok"
      },
      "profile_snapshot": {
        "display_name": "TikTok",
        "follower_count": 123456,
        "following_count": 12,
        "post_count": 34,
        "signature": "bio"
      },
      "enabled": true,
      "added_at": "2026-04-27T00:00:00+08:00"
    }
  ]
}
```

### 添加抖音/TikTok 账号

1. 优先让用户提供主页链接或分享文本。
2. 先解析 `sec_user_id`：

```bash
python3 <skill-dir>/scripts/extract_sec_user_id.py --workspace ~/douyin-vibe-track --platform douyin "<homepage-or-share-text>"
```

3. 再查询用户信息：

```bash
python3 <skill-dir>/scripts/fetch_user_profile.py --workspace ~/douyin-vibe-track --platform douyin --sec-user-id <sec_user_id>
```

### 添加视频号账号

1. 优先让用户提供 `username`（通常形如 `xxx@finder`）或明确主页信息。
2. 解析账号：

```bash
python3 <skill-dir>/scripts/extract_sec_user_id.py --workspace ~/douyin-vibe-track --platform wechat_channels "<username-or-share-text>"
```

3. 查询用户信息：

```bash
python3 <skill-dir>/scripts/fetch_user_profile.py --workspace ~/douyin-vibe-track --platform wechat_channels --username <username>
```

如果用户只给关键词，解析脚本会调用 TikHub 搜索接口并返回候选 `username`；Agent 必须向用户确认后再写入 `accounts.json`。

### 添加快手账号

1. 让用户提供该账号任意一条快手视频 URL，不再支持通过主页链接添加账号。
2. 先解析身份：

```bash
python3 <skill-dir>/scripts/extract_sec_user_id.py --workspace ~/douyin-vibe-track --platform kuaishou "<video-url-or-share-text>"
```

说明：
- 视频 URL 会先调用 TikHub `fetch_one_video_by_url`，从视频详情里提取纯数字 `user_id`，必要时同时补充 `eid`。

3. 再查询用户信息：

```bash
python3 <skill-dir>/scripts/fetch_user_profile.py --workspace ~/douyin-vibe-track --platform kuaishou --user-id <numeric_user_id>
```

删除、禁用、启用或查看账号时，直接编辑或读取 `accounts.json`。匹配账号时优先使用 `homepage_url` 或平台主标识，然后是 `display_name`。

## 执行每日报告

执行一次监控流程时：

1. 确保工作目录存在。
2. 确保 `config.json` 中有 `tikhub_api_key`。
3. 确保依赖已安装：

```bash
python3 -m pip install -r <skill-dir>/requirements.txt
```

还要确保系统已安装 `ffmpeg`，并且如果要处理视频号加密视频，系统里还要有 `node`。

4. 运行：

```bash
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track
```

如果某个账号失败，或者需要只获取单个用户数据，不要重新跑全量流程，改用单账号参数：

```bash
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --platform douyin --sec-user-id <sec_user_id>
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --platform wechat_channels --username <username>
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --platform kuaishou --eid <eid>
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --account <display_name_or_identity>
```

当这些单账号命令来自 `issues.json.recovery_commands` 时，命令会带 `--resume-report`。这表示脚本只重抓该账号，但会复用当天其他账号已完成的 `accounts/*.json`，并在该账号修复成功后继续完成视频下载和 PPT 生成，无需再手动补跑一次全量命令。

脚本会按平台调用 TikHub 对应接口，筛选最近 `lookback_hours` 小时内、且达到平台阈值 `thresholds.<platform>.like_count` 的作品，并排除已在 `state.json.reported_post_keys` 中出现过的 `<platform>:<post_id>`。

输出写入 `<reports_dir 或 ~/douyin-vibe-track/reports>/YYYY-MM-DD/`：

- `accounts/*.json`：每个账号独立的最终结果文件，顶层字段为 `status`、`generated_at`、`account`、`candidates`
- `accounts/*.json` 中的 `candidates`：最终命中的作品列表；后续汇总、下载和生成 PPT 都应读取这个字段
- `posts`：仅是脚本抓取阶段在内存中使用的原始帖子列表，不会写入 `accounts/*.json`，Agent 不应依赖该字段
- `videos/*.mp4`：下载并规范化后的命中视频
- `summary.pptx`：唯一的跨平台日报
- `issues.json`：仅在出现可恢复错误时生成

视频号下载后会先走本地解密，再走 `ffmpeg` 规范化，最后嵌入 PPT。

## 失败处理

脚本会为 API 和下载请求设置超时，并对失败请求最多重试 `max_retries` 次，默认 3 次。

如果脚本以非 0 状态退出，先看 stdout 末尾 JSON 的 `status`、`report_dir`、`issues` 和 `recovery_commands`；如果已经生成 `report_dir/issues.json`，优先读取该文件。Agent 必须按其中的 `fix` 和 `command` 继续处理，直到日报和视频结果完成。

Agent 恢复流程必须按循环执行，而不是只做一轮：

1. 读取最新的 `issues.json` 或 stdout 末尾 JSON。
2. 优先执行其中给出的 `recovery_commands`；这些命令通常只重跑失败账号，并在成功后自动继续完成剩余报告步骤。
3. 每执行完一轮后，重新读取最新的 `issues.json`。
4. 如果 `issues` 仍然存在但内容已经变化，继续处理新的剩余问题。
5. 只有在 `status=completed` 时才算结束；不要因为某个单账号重试一次后仍失败就停止整个恢复流程。
6. 如果同一问题连续多轮完全无变化，再向用户报告具体阻塞点和已尝试命令。

- 缺少 API key：配置 `config.json`；不要让脚本提示输入。
- 缺少依赖：安装 `requirements.txt`；视频号解密还要确认 `node` 可用。
- 没有启用的账号：询问用户要添加哪个平台的哪个账号。
- 获取作品失败：优先执行 `recovery_commands` 中对应账号的单账号命令；已经成功写入 `accounts/*.json` 的账号不要重复抓取。
- 视频号解密失败：确认系统 `node` 可用、仓库里的 `scripts/vendor/wechat_channels/*` 存在，并检查 TikHub 返回的 `decode_key`。
- PPT 生成失败：先确认所有 `accounts/*.json` 是否齐全、视频是否已经下载，再修复 `python-pptx` 或 `ffmpeg` 环境，然后重跑脚本。

不要在后续每日报告中重复包含之前已经入报的视频。
