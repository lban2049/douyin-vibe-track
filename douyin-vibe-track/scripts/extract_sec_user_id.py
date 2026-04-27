#!/usr/bin/env python3
"""Extract sec_user_id values from Douyin/TikTok homepage links via TikHub."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests


ENDPOINTS = {
    "douyin": "https://api.tikhub.io/api/v1/douyin/web/get_all_sec_user_id",
    "tiktok": "https://api.tikhub.io/api/v1/tiktok/web/get_all_sec_user_id",
}


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def infer_platform(values: list[str]) -> str:
    joined = " ".join(values).lower()
    if "tiktok.com" in joined:
        return "tiktok"
    return "douyin"


def request_json(
    url: str,
    *,
    headers: dict[str, str],
    body: list[str],
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, 200, None):
                raise RuntimeError(f"TikHub error: {payload.get('message') or payload.get('message_zh') or payload.get('code')}")
            return payload
        except Exception as exc:  # noqa: BLE001 - command line utility should preserve final failure.
            last_error = exc
            if attempt < max_retries:
                time.sleep(min(2 ** (attempt - 1), 8))
    raise RuntimeError(f"request failed after {max_retries} attempts: {last_error}") from last_error


def find_sec_user_ids(value: Any) -> list[str]:
    found: list[str] = []

    def add(candidate: Any) -> None:
        if not isinstance(candidate, str):
            return
        for match in re.findall(r"MS4w[0-9A-Za-z_.-]+", candidate):
            if match not in found:
                found.append(match)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key in {"sec_user_id", "sec_uid", "user_id"}:
                    add(child)
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)
        else:
            add(node)

    walk(value)
    return found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract sec_user_id from Douyin/TikTok homepage links.")
    parser.add_argument("--workspace", default=str(Path.home() / "douyin-vibe-track"))
    parser.add_argument("--platform", choices=("auto", "douyin", "tiktok"), default="auto")
    parser.add_argument("links", nargs="+", help="Homepage/share text/link values to parse.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser()
    config = load_json(workspace / "config.json", {})
    api_key = config.get("tikhub_api_key") or ""
    if not api_key:
        print("Missing tikhub_api_key in config.json. Configure it before running this script.", file=sys.stderr)
        return 2

    platform = infer_platform(args.links) if args.platform == "auto" else args.platform
    timeout = int(config.get("request_timeout_seconds") or 30)
    max_retries = int(config.get("max_retries") or 3)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    payload = request_json(ENDPOINTS[platform], headers=headers, body=args.links, timeout=timeout, max_retries=max_retries)
    sec_user_ids = find_sec_user_ids(payload)
    if not sec_user_ids:
        print("No sec_user_id found in TikHub response.", file=sys.stderr)
        print(json.dumps(payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    result = {
        "platform": platform,
        "sec_user_ids": sec_user_ids,
        "first_sec_user_id": sec_user_ids[0],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
