#!/usr/bin/env python3
"""Run one daily Douyin/TikTok account monitoring pass."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests


POSTS_URL = "https://api.tikhub.io/api/v1/douyin/app/v3/fetch_user_post_videos"


@dataclass
class Candidate:
    aweme_id: str
    author_name: str
    unique_id: str
    sec_user_id: str
    desc: str
    share_url: str
    create_time: int
    digg_count: int
    collect_count: int
    share_count: int
    forward_count: int
    video_urls: list[str]
    video_path: str = ""


@dataclass
class RunIssue:
    phase: str
    message: str
    fix: str
    account: str = ""
    aweme_id: str = ""
    command: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            key: value
            for key, value in {
                "phase": self.phase,
                "account": self.account,
                "aweme_id": self.aweme_id,
                "message": self.message,
                "fix": self.fix,
                "command": self.command,
            }.items()
            if value
        }


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def resolve_reports_root(workspace: Path, config: dict[str, Any]) -> Path:
    raw_reports_dir = str(config.get("reports_dir") or "").strip()
    if not raw_reports_dir:
        return workspace / "reports"

    reports_root = Path(raw_reports_dir).expanduser()
    if not reports_root.is_absolute():
        reports_root = workspace / reports_root
    return reports_root


def account_label(account: dict[str, Any]) -> str:
    return str(
        account.get("display_name")
        or account.get("unique_id")
        or account.get("user_id")
        or account.get("sec_user_id")
        or "unknown-account"
    )


def account_retry_command(workspace: Path, account: dict[str, Any]) -> str:
    if account.get("sec_user_id"):
        return f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --sec-user-id {shell_quote(str(account['sec_user_id']))}"
    if account.get("user_id"):
        return f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --user-id {shell_quote(str(account['user_id']))}"
    if account.get("unique_id"):
        return f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --unique-id {shell_quote(str(account['unique_id']))}"
    identifier = account_label(account)
    return f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --account {shell_quote(str(identifier))}"


def account_matches(account: dict[str, Any], value: str) -> bool:
    if not value:
        return True
    needle = value.strip().lower()
    keys = ("display_name", "homepage_url", "sec_user_id", "user_id", "unique_id")
    return any(str(account.get(key) or "").strip().lower() == needle for key in keys)


def filter_accounts(accounts: list[dict[str, Any]], args: argparse.Namespace, workspace: Path) -> tuple[list[dict[str, Any]], list[RunIssue]]:
    issues: list[RunIssue] = []
    selected = [account for account in accounts if account.get("enabled", True)]

    if args.sec_user_id or args.user_id or args.unique_id:
        requested = {
            "sec_user_id": args.sec_user_id,
            "user_id": args.user_id,
            "unique_id": args.unique_id,
        }
        matched = [
            account
            for account in selected
            if all(not value or str(account.get(key) or "").strip().lower() == value.strip().lower() for key, value in requested.items())
        ]
        selected = matched or [
            {
                "display_name": args.account or args.unique_id or args.user_id or args.sec_user_id,
                "sec_user_id": args.sec_user_id or "",
                "user_id": args.user_id or "",
                "unique_id": args.unique_id or "",
                "enabled": True,
                "_direct": True,
            }
        ]
    elif args.account:
        selected = [account for account in selected if account_matches(account, args.account)]
        if not selected:
            issues.append(
                RunIssue(
                    phase="select_account",
                    account=args.account,
                    message=f"no enabled account matched {args.account!r} in accounts.json",
                    fix="Check accounts.json, then retry with --account using display_name, sec_user_id, unique_id, user_id, or homepage_url. If the user is not configured, retry with --sec-user-id after extracting it from the profile link.",
                    command=f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --account <display_name_or_sec_user_id>",
                )
            )

    return selected, issues


def account_data_path(accounts_dir: Path, account: dict[str, Any]) -> Path:
    identity = account.get("sec_user_id") or account.get("user_id") or account.get("unique_id") or account_label(account)
    return accounts_dir / f"{sanitize_filename(str(identity))}.json"


def candidate_from_dict(data: dict[str, Any]) -> Candidate:
    return Candidate(
        aweme_id=str(data.get("aweme_id") or ""),
        author_name=str(data.get("author_name") or ""),
        unique_id=str(data.get("unique_id") or ""),
        sec_user_id=str(data.get("sec_user_id") or ""),
        desc=str(data.get("desc") or ""),
        share_url=str(data.get("share_url") or ""),
        create_time=int(data.get("create_time") or 0),
        digg_count=int(data.get("digg_count") or 0),
        collect_count=int(data.get("collect_count") or 0),
        share_count=int(data.get("share_count") or 0),
        forward_count=int(data.get("forward_count") or 0),
        video_urls=[str(url) for url in data.get("video_urls") or []],
        video_path=str(data.get("video_path") or ""),
    )


def read_completed_account_candidates(path: Path) -> list[Candidate] | None:
    try:
        payload = load_json(path, {})
    except Exception:
        return None
    if payload.get("status") != "completed":
        return None
    return [candidate_from_dict(item) for item in payload.get("candidates") or []]


def write_account_candidates(path: Path, account: dict[str, Any], candidates: list[Candidate], generated_at: datetime) -> None:
    write_json(
        path,
        {
            "status": "completed",
            "generated_at": generated_at.isoformat(),
            "account": {
                "display_name": account.get("display_name") or "",
                "sec_user_id": account.get("sec_user_id") or "",
                "user_id": account.get("user_id") or "",
                "unique_id": account.get("unique_id") or "",
                "homepage_url": account.get("homepage_url") or "",
            },
            "candidates": [asdict(candidate) for candidate in candidates],
        },
    )


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, Any],
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, 200, None):
                raise RuntimeError(f"TikHub error: {payload.get('message') or payload.get('message_zh') or payload.get('code')}")
            return payload
        except Exception as exc:  # noqa: BLE001 - retain final error for CLI.
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"request failed after {max_retries} attempts: {last_error}") from last_error


def download_file(urls: list[str], destination: Path, timeout: int, max_retries: int) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for url in urls:
        for attempt in range(1, max_retries + 1):
            try:
                with requests.get(url, stream=True, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"}) as response:
                    response.raise_for_status()
                    tmp = destination.with_suffix(destination.suffix + ".tmp")
                    with tmp.open("wb") as fh:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                fh.write(chunk)
                    tmp.replace(destination)
                    return destination
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < max_retries:
                    time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"download failed after trying {len(urls)} URLs: {last_error}") from last_error


def normalize_video_for_ppt(source: Path, destination: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        if source != destination:
            source.replace(destination)
        return destination

    tmp = destination.with_name(f"{destination.stem}.ppt-tmp.mp4")
    command = [
        ffmpeg,
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-profile:v",
        "main",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    tmp.replace(destination)
    if source != destination and source.exists():
        source.unlink()
    return destination


def extract_poster_frame(video_path: Path) -> Path | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    poster_path = video_path.with_suffix(".jpg")
    command = [
        ffmpeg,
        "-y",
        "-ss",
        "00:00:01",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(poster_path),
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        return None
    return poster_path if poster_path.exists() else None


def unwrap_posts(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if isinstance(data, dict) and isinstance(data.get("aweme_list"), list):
        return data
    raise RuntimeError("could not find aweme_list in TikHub response")


def collect_video_urls(item: dict[str, Any]) -> list[str]:
    video = item.get("video") or {}
    urls: list[str] = []
    for key in ("download_no_watermark_addr", "play_addr", "download_addr"):
        address = video.get(key) or {}
        for url in address.get("url_list") or []:
            if url and url not in urls:
                urls.append(url)
    return urls


def to_candidate(item: dict[str, Any]) -> Candidate:
    author = item.get("author") or {}
    stats = item.get("statistics") or {}
    aweme_id = str(item.get("aweme_id") or stats.get("aweme_id") or item.get("id") or "")
    return Candidate(
        aweme_id=aweme_id,
        author_name=author.get("nickname") or "",
        unique_id=author.get("unique_id") or "",
        sec_user_id=author.get("sec_uid") or "",
        desc=item.get("desc") or "",
        share_url=item.get("share_url") or "",
        create_time=int(item.get("create_time") or 0),
        digg_count=int(stats.get("digg_count") or 0),
        collect_count=int(stats.get("collect_count") or 0),
        share_count=int(stats.get("share_count") or 0),
        forward_count=int(stats.get("forward_count") or stats.get("repost_count") or 0),
        video_urls=collect_video_urls(item),
    )


def sanitize_filename(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|\s]+', "_", value).strip("._ ")
    return value[:120] or "video"


def format_time(epoch_seconds: int, tz: ZoneInfo) -> str:
    if not epoch_seconds:
        return ""
    return datetime.fromtimestamp(epoch_seconds, tz).strftime("%Y-%m-%d %H:%M:%S")


def format_filename_time(epoch_seconds: int, tz: ZoneInfo) -> str:
    if not epoch_seconds:
        return "unknown-time"
    return datetime.fromtimestamp(epoch_seconds, tz).strftime("%Y-%m-%d_%H-%M-%S")


def make_video_destination(videos_dir: Path, item: Candidate, tz: ZoneInfo) -> Path:
    author = sanitize_filename(item.author_name or item.unique_id or item.aweme_id)
    created_at = format_filename_time(item.create_time, tz)
    destination = videos_dir / f"{author}-{created_at}.mp4"
    if not destination.exists():
        return destination

    for index in range(2, 1000):
        candidate = videos_dir / f"{author}-{created_at}-{index}.mp4"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not find available filename for {author}-{created_at}")


def load_pptx_dependencies() -> tuple[Any, Any, Any]:
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
    except ImportError as exc:  # pragma: no cover - exercised by environment.
        raise RuntimeError("Missing dependency python-pptx. Install with: python3 -m pip install -r requirements.txt") from exc
    return Presentation, Inches, Pt


def iter_recent_posts(
    account: dict[str, Any],
    headers: dict[str, str],
    config: dict[str, Any],
    since_epoch: int,
    workspace: Path,
) -> tuple[list[dict[str, Any]], list[RunIssue]]:
    timeout = int(config.get("request_timeout_seconds") or 30)
    max_retries = int(config.get("max_retries") or 3)
    count = int(config.get("page_count") or 20)
    sort_type = int(config.get("sort_type") or 0)
    posts: list[dict[str, Any]] = []
    errors: list[RunIssue] = []
    max_cursor: int | str = 0

    for _ in range(20):
        params = {
            "sec_user_id": account.get("sec_user_id") or "",
            "user_id": account.get("user_id") or "",
            "unique_id": account.get("unique_id") or "",
            "max_cursor": max_cursor,
            "count": count,
            "sort_type": sort_type,
        }
        try:
            data = unwrap_posts(request_json(POSTS_URL, headers=headers, params=params, timeout=timeout, max_retries=max_retries))
        except Exception as exc:  # noqa: BLE001
            errors.append(
                RunIssue(
                    phase="fetch_posts",
                    account=account_label(account),
                    message=str(exc),
                    fix="Retry this account only. If it still fails, verify the account sec_user_id with fetch_user_profile.py, check the TikHub API key/quota, and increase request_timeout_seconds or max_retries in config.json for transient network failures.",
                    command=account_retry_command(workspace, account),
                )
            )
            break

        aweme_list = data.get("aweme_list") or []
        if not aweme_list:
            break

        posts.extend(aweme_list)
        oldest = min(int(item.get("create_time") or 0) for item in aweme_list)
        if oldest and oldest < since_epoch:
            break

        if not data.get("has_more"):
            break
        next_cursor = data.get("max_cursor")
        if not next_cursor or next_cursor == max_cursor:
            break
        max_cursor = next_cursor

    return posts, errors


def build_pptx(path: Path, candidates: list[Candidate], tz: ZoneInfo) -> None:
    Presentation, Inches, Pt = load_pptx_dependencies()
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    poster_frames: list[Path] = []

    if not candidates:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        box = slide.shapes.add_textbox(Inches(0.8), Inches(0.8), Inches(11.8), Inches(1.5))
        text = box.text_frame
        text.text = "今日无点赞超过阈值的新作品"
        text.paragraphs[0].font.size = Pt(34)
        prs.save(path)
        return

    for item in candidates:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        video_path = Path(item.video_path)
        if video_path.exists():
            poster_frame = extract_poster_frame(video_path)
            if poster_frame:
                poster_frames.append(poster_frame)
            slide.shapes.add_movie(
                str(video_path),
                Inches(0.35),
                Inches(0.35),
                Inches(6.2),
                Inches(6.8),
                poster_frame_image=str(poster_frame) if poster_frame else None,
                mime_type="video/mp4",
            )

        title_box = slide.shapes.add_textbox(Inches(6.9), Inches(0.55), Inches(5.8), Inches(0.8))
        title_frame = title_box.text_frame
        title_frame.text = item.author_name or item.unique_id or item.aweme_id
        title_frame.paragraphs[0].font.size = Pt(26)
        title_frame.paragraphs[0].font.bold = True

        details = [
            ("博主名称", item.author_name or item.unique_id or item.aweme_id),
            ("点赞数", item.digg_count),
            ("收藏数", item.collect_count),
            ("分享数", item.share_count),
            ("发布时间", format_time(item.create_time, tz)),
        ]
        body = slide.shapes.add_textbox(Inches(6.9), Inches(1.55), Inches(5.8), Inches(4.9)).text_frame
        body.word_wrap = True
        body.text = ""
        for label, value in details:
            paragraph = body.add_paragraph()
            paragraph.text = f"{label}: {value}"
            paragraph.font.size = Pt(18)

    prs.save(path)
    for poster_frame in poster_frames:
        poster_frame.unlink(missing_ok=True)


def print_issues(issues: list[RunIssue]) -> None:
    for issue in issues:
        prefix_parts = [issue.phase]
        if issue.account:
            prefix_parts.append(f"account={issue.account}")
        if issue.aweme_id:
            prefix_parts.append(f"aweme_id={issue.aweme_id}")
        print(f"[ERROR] {' '.join(prefix_parts)}: {issue.message}", file=sys.stderr)
        print(f"[FIX] {issue.fix}", file=sys.stderr)
        if issue.command:
            print(f"[RETRY] {issue.command}", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one daily Douyin/TikTok monitoring pass.")
    parser.add_argument("--workspace", default=str(Path.home() / "douyin-vibe-track"))
    parser.add_argument("--account", default="", help="Run only one configured account, matched by display_name, homepage_url, sec_user_id, user_id, or unique_id.")
    parser.add_argument("--sec-user-id", default="", help="Run one user directly by sec_user_id without scanning every configured account.")
    parser.add_argument("--user-id", default="", help="Run one user directly by user_id, or match a configured account by user_id.")
    parser.add_argument("--unique-id", default="", help="Run one user directly by unique_id, or match a configured account by unique_id.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser()
    config_path = workspace / "config.json"
    accounts_path = workspace / "accounts.json"
    state_path = workspace / "state.json"

    try:
        config = load_json(config_path, {})
        accounts_data = load_json(accounts_path, {"accounts": []})
        state = load_json(state_path, {"last_run_at": None, "reported_aweme_ids": []})
    except Exception as exc:  # noqa: BLE001
        print_issues(
            [
                RunIssue(
                    phase="load_workspace",
                    message=str(exc),
                    fix="Check config.json, accounts.json, and state.json for invalid JSON or unreadable files. Repair the file named in the error, then rerun the command.",
                )
            ]
        )
        return 2

    api_key = config.get("tikhub_api_key") or ""
    if not api_key:
        print_issues(
            [
                RunIssue(
                    phase="config",
                    message=f"missing tikhub_api_key in {config_path}",
                    fix="Configure config.json with a valid TikHub API key before running. Do not prompt inside the script; the Agent should ask the user for the key or use an existing configured key.",
                )
            ]
        )
        return 2

    configured_enabled_accounts = [account for account in accounts_data.get("accounts", []) if account.get("enabled", True)]
    enabled_accounts, selection_issues = filter_accounts(accounts_data.get("accounts", []), args, workspace)
    if selection_issues:
        print_issues(selection_issues)
        print(json.dumps({"status": "failed", "errors": [issue.to_dict() for issue in selection_issues]}, ensure_ascii=False, indent=2))
        return 2
    if not enabled_accounts:
        print_issues(
            [
                RunIssue(
                    phase="select_account",
                    message=f"no enabled accounts in {accounts_path}",
                    fix="Add or enable at least one account in accounts.json. If the user provided only a Douyin profile link, first run extract_sec_user_id.py, confirm with fetch_user_profile.py, then add the account.",
                )
            ]
        )
        return 2

    try:
        load_pptx_dependencies()
    except RuntimeError as exc:
        print_issues(
            [
                RunIssue(
                    phase="dependencies",
                    message=str(exc),
                    fix="Install dependencies with: python3 -m pip install -r douyin-vibe-track/requirements.txt",
                )
            ]
        )
        return 2

    tz = ZoneInfo(config.get("timezone") or "Asia/Shanghai")
    now = datetime.now(tz)
    report_date = now.strftime("%Y-%m-%d")
    lookback_hours = int(config.get("lookback_hours") or 72)
    since = now - timedelta(hours=lookback_hours)
    since_epoch = int(since.timestamp())
    like_threshold = int(config.get("like_threshold") or 10000)
    max_retries = int(config.get("max_retries") or 3)
    download_timeout = int(config.get("download_timeout_seconds") or 120)
    reported_ids = {str(value) for value in state.get("reported_aweme_ids", [])}
    headers = {"Authorization": f"Bearer {api_key}"}

    reports_root = resolve_reports_root(workspace, config)
    report_dir = reports_root / report_date
    accounts_dir = report_dir / "accounts"
    videos_dir = report_dir / "videos"
    accounts_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(parents=True, exist_ok=True)

    accounts_for_report = enabled_accounts if any(account.get("_direct") for account in enabled_accounts) else configured_enabled_accounts
    errors: list[RunIssue] = []

    for account in enabled_accounts:
        data_path = account_data_path(accounts_dir, account)
        if read_completed_account_candidates(data_path) is not None:
            continue

        posts, account_errors = iter_recent_posts(account, headers, config, since_epoch, workspace)
        errors.extend(account_errors)
        if account_errors:
            continue

        account_candidates: list[Candidate] = []
        account_issues: list[RunIssue] = []
        seen_account: set[str] = set()
        for post in posts:
            candidate = to_candidate(post)
            if not candidate.aweme_id:
                continue
            if candidate.aweme_id in reported_ids or candidate.aweme_id in seen_account:
                continue
            if candidate.create_time < since_epoch:
                continue
            if candidate.digg_count < like_threshold:
                continue
            if not candidate.video_urls:
                account_issues.append(
                    RunIssue(
                        phase="collect_video_url",
                        account=candidate.author_name or candidate.unique_id or account_label(account),
                        aweme_id=candidate.aweme_id,
                        message="no downloadable video URL found in TikHub response",
                        fix="Retry this account only. If the response still has no video URL, inspect the raw TikHub response for this aweme_id or use another TikHub endpoint/source for the video URL, then rerun the account.",
                        command=account_retry_command(workspace, account),
                    )
                )
                continue
            seen_account.add(candidate.aweme_id)
            account_candidates.append(candidate)

        if account_issues:
            errors.extend(account_issues)
            continue
        account_candidates.sort(key=lambda item: (item.digg_count, item.create_time), reverse=True)
        write_account_candidates(data_path, account, account_candidates, now)

    candidates: list[Candidate] = []
    missing_accounts: list[dict[str, Any]] = []
    for account in accounts_for_report:
        account_candidates = read_completed_account_candidates(account_data_path(accounts_dir, account))
        if account_candidates is None:
            missing_accounts.append(account)
            continue
        candidates.extend(account_candidates)

    existing_error_accounts = {issue.account for issue in errors if issue.account}
    for account in missing_accounts:
        if account_label(account) in existing_error_accounts:
            continue
        errors.append(
            RunIssue(
                phase="account_data",
                account=account_label(account),
                message=f"missing completed account data file: {account_data_path(accounts_dir, account)}",
                fix="Fetch this account only. The daily PPT will be generated only after every enabled account has a completed JSON data file for today.",
                command=account_retry_command(workspace, account),
            )
        )

    if errors:
        issue_payload = {
            "status": "needs_repair",
            "generated_at": now.isoformat(),
            "issues": [issue.to_dict() for issue in errors],
            "recovery_commands": sorted({issue.command for issue in errors if issue.command}),
        }
        write_json(report_dir / "issues.json", issue_payload)
        print_issues(errors)
        print(
            json.dumps(
                {
                    "status": "needs_repair",
                    "report_dir": str(report_dir),
                    "account_data_dir": str(accounts_dir),
                    "pptx": str(report_dir / "summary.pptx"),
                    "videos": 0,
                    "errors": len(errors),
                    "issues": [issue.to_dict() for issue in errors],
                    "recovery_commands": issue_payload["recovery_commands"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    candidates.sort(key=lambda item: (item.digg_count, item.create_time), reverse=True)

    for item in candidates:
        video_stem = f"{sanitize_filename(item.author_name or item.unique_id or item.aweme_id)}-{format_filename_time(item.create_time, tz)}"
        existing_video = next(
            (
                path
                for path in videos_dir.iterdir()
                if path.suffix == ".mp4"
                and not path.name.endswith(".raw.mp4")
                and ".ppt-tmp." not in path.name
                and (path.stem == video_stem or path.stem.startswith(f"{video_stem}-"))
            ),
            None,
        )
        if existing_video:
            item.video_path = str(existing_video)
            continue

        destination = make_video_destination(videos_dir, item, tz)
        raw_destination = destination.with_name(f"{destination.stem}.raw.mp4")
        try:
            download_file(item.video_urls, raw_destination, download_timeout, max_retries)
            normalize_video_for_ppt(raw_destination, destination)
            item.video_path = str(destination)
        except Exception as exc:  # noqa: BLE001
            errors.append(
                RunIssue(
                    phase="download_video",
                    account=item.author_name or item.unique_id or item.sec_user_id,
                    aweme_id=item.aweme_id,
                    message=str(exc),
                    fix="Retry this account only. If it still fails, verify that the video URL has not expired, increase download_timeout_seconds/max_retries in config.json for slow networks, or fetch fresh post data before downloading again.",
                    command=(
                        f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --sec-user-id {shell_quote(item.sec_user_id)}"
                        if item.sec_user_id
                        else f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))} --account {shell_quote(item.unique_id or item.author_name)}"
                    ),
                )
            )

    written_candidates = [item for item in candidates if item.video_path]
    if errors:
        issue_payload = {
            "status": "needs_repair",
            "generated_at": now.isoformat(),
            "issues": [issue.to_dict() for issue in errors],
            "recovery_commands": sorted({issue.command for issue in errors if issue.command}),
        }
        write_json(report_dir / "issues.json", issue_payload)
        print_issues(errors)
        print(
            json.dumps(
                {
                    "status": "needs_repair",
                    "report_dir": str(report_dir),
                    "account_data_dir": str(accounts_dir),
                    "pptx": str(report_dir / "summary.pptx"),
                    "videos": len(written_candidates),
                    "errors": len(errors),
                    "issues": [issue.to_dict() for issue in errors],
                    "recovery_commands": issue_payload["recovery_commands"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    pptx_built = False
    try:
        build_pptx(report_dir / "summary.pptx", written_candidates, tz)
        pptx_built = True
    except Exception as exc:  # noqa: BLE001
        errors.append(
            RunIssue(
                phase="build_pptx",
                message=str(exc),
                fix="The videos may already be downloaded. Check the listed video paths, install or repair python-pptx/ffmpeg if needed, then rerun the same command after fixing the PPT generation error.",
                command=f"python3 douyin-vibe-track/scripts/run_daily.py --workspace {shell_quote(str(workspace))}",
            )
        )

    state["last_run_at"] = now.isoformat()
    state["reported_aweme_ids"] = sorted(reported_ids | {item.aweme_id for item in written_candidates}) if pptx_built else sorted(reported_ids)
    write_json(state_path, state)

    if errors:
        issue_payload = {
            "status": "needs_repair",
            "generated_at": now.isoformat(),
            "issues": [issue.to_dict() for issue in errors],
            "recovery_commands": sorted({issue.command for issue in errors if issue.command}),
        }
        write_json(report_dir / "issues.json", issue_payload)
        print_issues(errors)
    recovery_commands = sorted({issue.command for issue in errors if issue.command})
    print(
        json.dumps(
            {
                "status": "needs_repair" if errors else "completed",
                "report_dir": str(report_dir),
                "pptx": str(report_dir / "summary.pptx"),
                "videos": len(written_candidates),
                "errors": len(errors),
                "issues": [issue.to_dict() for issue in errors],
                "recovery_commands": recovery_commands,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
