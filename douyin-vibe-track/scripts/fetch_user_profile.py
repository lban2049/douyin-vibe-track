#!/usr/bin/env python3
"""Fetch and summarize a TikHub user profile for account confirmation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests


PROFILE_URLS = {
    "douyin": "https://api.tikhub.io/api/v1/douyin/app/v3/handler_user_profile",
    "tiktok": "https://api.tikhub.io/api/v1/tiktok/app/v3/handler_user_profile",
}


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str],
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
        except Exception as exc:  # noqa: BLE001 - preserve concise CLI failure behavior.
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"request failed after {max_retries} attempts: {last_error}") from last_error


def unwrap_profile(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if isinstance(data, dict):
        for key in ("user", "user_info", "aweme_user_info"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        if "uid" in data or "unique_id" in data or "sec_uid" in data:
            return data
    raise RuntimeError("could not find user profile data in TikHub response")


def summarize_profile(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "display_name": profile.get("nickname") or profile.get("display_name") or "",
        "unique_id": profile.get("unique_id") or "",
        "user_id": str(profile.get("uid") or profile.get("user_id") or ""),
        "sec_user_id": profile.get("sec_uid") or profile.get("sec_user_id") or "",
        "follower_count": profile.get("follower_count") or profile.get("followers_count") or 0,
        "following_count": profile.get("following_count") or 0,
        "aweme_count": profile.get("aweme_count") or 0,
        "signature": profile.get("signature") or "",
        "region": profile.get("region") or profile.get("account_region") or "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch TikHub user profile for confirmation.")
    parser.add_argument("--workspace", default=str(Path.home() / "douyin-vibe-track"))
    parser.add_argument("--platform", choices=("douyin", "tiktok"), default="douyin")
    parser.add_argument("--sec-user-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--unique-id", default="")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON summary.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser()
    config = load_json(workspace / "config.json", {})
    api_key = config.get("tikhub_api_key") or ""
    if not api_key:
        print("Missing tikhub_api_key in config.json. Configure it before running this script.", file=sys.stderr)
        return 2

    params = {
        "user_id": args.user_id or "",
        "sec_user_id": args.sec_user_id or "",
        "unique_id": args.unique_id or "",
    }
    if not any(params.values()):
        print("Provide one of --sec-user-id, --user-id, or --unique-id.", file=sys.stderr)
        return 2

    timeout = int(config.get("request_timeout_seconds") or 30)
    max_retries = int(config.get("max_retries") or 3)
    headers = {"Authorization": f"Bearer {api_key}"}

    payload = request_json(PROFILE_URLS[args.platform], headers=headers, params=params, timeout=timeout, max_retries=max_retries)
    summary = summarize_profile(unwrap_profile(payload))

    if args.json_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("Account profile:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
