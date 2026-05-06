#!/usr/bin/env python3
"""Fetch and summarize a TikHub user profile for account confirmation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platform_core import fetch_profile, infer_platform_from_text, normalize_platform, summarize_profile


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch TikHub user profile for confirmation.")
    parser.add_argument("--workspace", default=str(Path.home() / "douyin-vibe-track"))
    parser.add_argument("--platform", choices=("auto", "douyin", "tiktok", "wechat_channels", "kuaishou"), default="douyin")
    parser.add_argument("--sec-user-id", default="")
    parser.add_argument("--user-id", default="")
    parser.add_argument("--unique-id", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--eid", default="")
    parser.add_argument("--json-only", action="store_true", help="Print only the JSON summary.")
    return parser.parse_args()


def build_identity(args: argparse.Namespace) -> dict[str, str]:
    return {
        "sec_user_id": args.sec_user_id or "",
        "user_id": args.user_id or "",
        "unique_id": args.unique_id or "",
        "username": args.username or "",
        "eid": args.eid or "",
    }


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser()
    identity = build_identity(args)

    platform = args.platform
    if platform == "auto":
        probe = " ".join(value for value in identity.values() if value)
        platform = infer_platform_from_text(probe)
    platform = normalize_platform(platform)

    if not any(identity.values()):
        print("Provide one of --sec-user-id, --user-id, --unique-id, --username, or --eid.", file=sys.stderr)
        return 2

    if platform == "kuaishou" and not (identity.get("eid") or identity.get("user_id")):
        print("Kuaishou requires --eid or --user-id.", file=sys.stderr)
        return 2
    if platform == "wechat_channels" and not identity.get("username"):
        print("wechat_channels requires --username.", file=sys.stderr)
        return 2

    try:
        profile = fetch_profile(workspace, platform, identity)
        summary = summarize_profile(platform, profile, identity=identity)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    if args.json_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0

    print("Account profile:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
