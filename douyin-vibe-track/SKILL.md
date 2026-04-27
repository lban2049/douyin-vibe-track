---
name: douyin-vibe-track
description: 监控已配置的抖音/TikTok 账号近期作品，确认并维护监控账号 ID，获取 TikHub 用户资料和主页作品数据，下载高点赞视频，并生成每日 PPT 报告。当用户要求添加、删除、查看或执行抖音/TikTok 账号监控，创建每日视频报告，或管理此流程的 TikHub API Key 时使用。
---

# Douyin Vibe Track

使用此 skill 管理本地监控工作目录，并对已配置的抖音/TikTok 账号执行一次每日扫描。外部定时框架负责每天调用此 skill；此 skill 只处理单次执行。

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
  "like_threshold": 10000,
  "request_timeout_seconds": 30,
  "download_timeout_seconds": 120,
  "max_retries": 3,
  "page_count": 20,
  "sort_type": 0
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
  "reported_aweme_ids": []
}
```

不要把 TikHub API Key 存入 skill 目录或仓库。

## API Key

从 `~/douyin-vibe-track/config.json` 读取 `tikhub_api_key`。

- 如果缺少 key，且用户已在当前对话中提供，写入 `config.json`。
- 如果缺少 key，且用户没有提供，在调用脚本前向用户索要 TikHub API Key。
- 不要让 `scripts/run_daily.py`、`scripts/extract_sec_user_id.py` 或 `scripts/fetch_user_profile.py` 提示用户输入 key。Agent 必须先完成 key 配置。

## 账号管理

当用户想添加监控账号时：

1. 确保工作目录和 API Key 已配置。
2. 优先让用户提供抖音用户主页链接或分享文本，例如 `https://www.douyin.com/user/...`、`https://v.douyin.com/...`，或“长按复制此条消息...”这类分享文案。
3. 先调用主页链接解析脚本提取 `sec_user_id`：

```bash
python3 <skill-dir>/scripts/extract_sec_user_id.py --workspace ~/douyin-vibe-track --platform douyin "<homepage-or-share-text>"
```

如果用户明确提供 TikTok 主页链接，改用 `--platform tiktok`。如果用户没有提供主页链接，只提供用户名或其他 ID，先请求用户提供主页链接；只有在用户无法提供链接时，才按可用信息手动尝试 `--sec-user-id`、`--user-id` 或 `--unique-id`。

4. 使用上一步得到的 `sec_user_id` 查询用户信息：

```bash
python3 <skill-dir>/scripts/fetch_user_profile.py --workspace ~/douyin-vibe-track --platform douyin --sec-user-id <sec_user_id>
```

5. 向用户展示返回的昵称、unique_id、uid、sec_user_id、粉丝数和签名。
6. 让用户确认这是否是要监控的账号。
7. 只有用户确认后，才在 `accounts.json` 中添加或更新该账号。

账号按以下结构保存：

```json
{
  "accounts": [
    {
      "display_name": "TikTok",
      "platform": "douyin",
      "homepage_url": "https://www.douyin.com/user/MS4w...",
      "sec_user_id": "MS4w...",
      "user_id": "107955",
      "unique_id": "tiktok",
      "enabled": true,
      "added_at": "2026-04-27T00:00:00+08:00"
    }
  ]
}
```

删除、禁用、启用或查看账号时，直接编辑或读取 `accounts.json`。匹配账号时优先使用 `homepage_url` 或 `sec_user_id`，然后是 `unique_id`，最后是 `user_id`。

## 执行每日报告

执行一次监控流程时：

1. 确保工作目录存在。
2. 确保 `config.json` 中有 `tikhub_api_key`。
3. 确保依赖已安装：

```bash
python3 -m pip install -r <skill-dir>/requirements.txt
```

4. 运行：

```bash
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track
```

如果某个账号失败，或者需要只获取单个用户数据，不要重新跑全量流程，改用单账号参数：

```bash
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --account <display_name_or_sec_user_id_or_unique_id>
python3 <skill-dir>/scripts/run_daily.py --workspace ~/douyin-vibe-track --sec-user-id <sec_user_id>
```

脚本会调用 TikHub `GET https://api.tikhub.io/api/v1/douyin/app/v3/fetch_user_post_videos`，并使用 `Authorization: Bearer <api_key>` 认证。

脚本检查最近 `lookback_hours` 小时内发布的作品，默认 72 小时。如果 `state.json` 中没有 `last_run_at`，仍然使用 72 小时窗口。脚本筛选 `statistics.digg_count >= like_threshold` 的作品，默认阈值为 10000，并排除已存在于 `reported_aweme_ids` 中的 `aweme_id`。

输出写入 `~/douyin-vibe-track/reports/YYYY-MM-DD/`：

- `accounts/*.json`：每个账号独立的抓取和过滤结果文件；即使没有符合阈值的作品，也会写入空的 `candidates`。这是当天该账号已成功处理的标记。
- `videos/*.mp4`：下载的命中视频。
- `summary.pptx`：唯一的日报文件。只有当天所有启用账号的 `accounts/*.json` 都成功生成后，脚本才会读取这些 JSON 汇总下载视频并生成 PPT。每个命中视频一页，左侧放可播放视频，右侧使用中文展示博主名称、点赞数、收藏数、分享数和发布时间；不要展示作品描述或链接。
- `issues.json`：仅在出现可恢复错误时生成，包含失败阶段、账号、作品 ID、明确原因、修复建议和单账号重试命令。

如果没有命中视频，脚本仍会创建 `summary.pptx`，并更新 `last_run_at`。

脚本会优先使用 `ffmpeg` 将下载的视频规范化为 PowerPoint 更兼容的 H.264/yuv420p/AAC MP4，并抽取视频封面作为 PPT poster frame。如果系统没有 `ffmpeg`，脚本仍会嵌入原始下载视频，但播放兼容性可能下降。

## 失败处理

脚本会为 API 和下载请求设置超时，并对失败请求最多重试 `max_retries` 次，默认 3 次。

如果脚本以非 0 状态退出，先看 stdout 末尾 JSON 的 `status`、`issues` 和 `recovery_commands`；如果已经生成 `reports/YYYY-MM-DD/issues.json`，优先读取该文件。Agent 必须按其中的 `fix` 和 `command` 继续处理，直到日报和视频结果完成。

- 缺少 API key：配置 `config.json`；不要让脚本提示输入。
- 缺少依赖：安装 `requirements.txt`。
- 没有启用的账号：询问用户要添加哪个账号。
- 无法从主页链接提取 `sec_user_id`：请用户提供完整抖音主页链接或分享文本。
- 获取作品失败：优先执行 `recovery_commands` 中对应账号的单账号命令；已经成功写入 `accounts/*.json` 的账号不要重复抓取。单账号修复成功后，脚本会检查当天所有账号 JSON 是否齐全，齐全后才生成 PPT。
- 下载视频失败：优先执行 `recovery_commands` 中对应账号的单账号命令以刷新视频 URL；如果仍失败，调大 `download_timeout_seconds` / `max_retries`，或改用新的视频下载源后重跑该账号。
- PPT 生成失败：先确认所有 `accounts/*.json` 是否齐全、视频是否已经下载，再修复 `python-pptx` 或 `ffmpeg` 环境，然后重跑脚本。PPT 生成失败时脚本不会把本轮视频写入 `reported_aweme_ids`，避免重跑时遗漏。

不要在后续每日报告中重复包含之前已经入报的视频。
