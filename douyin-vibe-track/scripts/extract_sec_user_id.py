#!/usr/bin/env python3
"""Resolve platform-specific account identities from links or share text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from platform_core import infer_platform_from_text, normalize_platform, resolve_account_identity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve account identity from homepage links/share text.")
    parser.add_argument("--workspace", default=str(Path.home() / "douyin-vibe-track"))
    parser.add_argument("--platform", choices=("auto", "douyin", "tiktok", "wechat_channels", "kuaishou"), default="auto")
    parser.add_argument("links", nargs="+", help="Homepage/share text/link values to parse.")
    return parser.parse_args()


def format_output(platform: str, resolved: dict[str, object]) -> dict[str, object]:
    identity = dict(resolved.get("identity") or {})
    result: dict[str, object] = {
        "platform": platform,
        "identity": identity,
    }
    if platform in {"douyin", "tiktok"}:
        sec_user_id = identity.get("sec_user_id") or ""
        result["sec_user_ids"] = list(resolved.get("candidates") or ([sec_user_id] if sec_user_id else []))
        result["first_sec_user_id"] = sec_user_id
    elif platform == "kuaishou":
        result["eid"] = identity.get("eid") or ""
    else:
        result["username"] = identity.get("username") or ""
        if resolved.get("candidates"):
            result["candidate_usernames"] = list(resolved.get("candidates") or [])
    return result


def main() -> int:
    args = parse_args()
    workspace = Path(args.workspace).expanduser()
    platform = infer_platform_from_text(" ".join(args.links)) if args.platform == "auto" else normalize_platform(args.platform)

    try:
        resolved = resolve_account_identity(workspace, platform, args.links)
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(format_output(platform, resolved), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
