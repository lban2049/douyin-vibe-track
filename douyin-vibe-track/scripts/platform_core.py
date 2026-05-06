#!/usr/bin/env python3
"""Shared helpers for multi-platform TikHub account monitoring."""

from __future__ import annotations

import json
import re
import threading
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from requests import Response, Session


PLATFORM_ALIASES = {
    "douyin": "douyin",
    "tiktok": "tiktok",
    "wechat": "wechat_channels",
    "wechat_channels": "wechat_channels",
    "channels": "wechat_channels",
    "video_channel": "wechat_channels",
    "kuaishou": "kuaishou",
    "ks": "kuaishou",
}

PLATFORM_LABELS = {
    "douyin": "抖音",
    "tiktok": "TikTok",
    "wechat_channels": "视频号",
    "kuaishou": "快手",
}

PROFILE_URLS = {
    "douyin": "https://api.tikhub.io/api/v1/douyin/app/v3/handler_user_profile",
    "tiktok": "https://api.tikhub.io/api/v1/tiktok/app/v3/handler_user_profile",
    "kuaishou": "https://api.tikhub.io/api/v1/kuaishou/web/fetch_user_info",
}

POSTS_URLS = {
    "douyin": "https://api.tikhub.io/api/v1/douyin/app/v3/fetch_user_post_videos",
    "tiktok": "https://api.tikhub.io/api/v1/tiktok/app/v3/fetch_user_post_videos",
    "kuaishou": "https://api.tikhub.io/api/v1/kuaishou/web/fetch_user_post",
    "kuaishou_app_v2": "https://api.tikhub.io/api/v1/kuaishou/app/fetch_user_post_v2",
    "kuaishou_hot_post": "https://api.tikhub.io/api/v1/kuaishou/app/fetch_user_hot_post",
    "wechat_channels": "https://api.tikhub.io/api/v1/wechat_channels/fetch_home_page",
}

WECHAT_USER_SEARCH_V2_URL = "https://api.tikhub.io/api/v1/wechat_channels/fetch_user_search_v2"
WECHAT_VIDEO_DETAIL_URL = "https://api.tikhub.io/api/v1/wechat_channels/fetch_video_detail"
DOUYIN_SEC_ID_URLS = {
    "douyin": "https://api.tikhub.io/api/v1/douyin/web/get_all_sec_user_id",
    "tiktok": "https://api.tikhub.io/api/v1/tiktok/web/get_all_sec_user_id",
}

_THREAD_LOCAL = threading.local()


def normalize_platform(value: str) -> str:
    platform = PLATFORM_ALIASES.get((value or "").strip().lower())
    if not platform:
        raise ValueError(f"unsupported platform: {value!r}")
    return platform


def platform_label(platform: str) -> str:
    return PLATFORM_LABELS.get(platform, platform)


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


def get_session() -> Session:
    session = getattr(_THREAD_LOCAL, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        _THREAD_LOCAL.session = session
    return session


def should_retry_response(response: Response, retryable_status_codes: set[int] | None = None) -> bool:
    codes = retryable_status_codes or {429, 500, 502, 503, 504}
    return response.status_code in codes


def should_retry_exception(exc: Exception, retryable_status_codes: set[int] | None = None) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return should_retry_response(exc.response, retryable_status_codes)
    return False


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    timeout: int | tuple[int, int],
    max_retries: int,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    session: Session | None = None,
    retryable_status_codes: set[int] | None = None,
) -> dict[str, Any]:
    last_error: Exception | None = None
    attempts_made = 0
    session = session or get_session()
    for attempt in range(1, max_retries + 1):
        attempts_made = attempt
        try:
            response = session.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_body,
                timeout=timeout,
            )
            if should_retry_response(response, retryable_status_codes):
                response.raise_for_status()
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") not in (0, 200, None):
                raise RuntimeError(f"TikHub error: {payload.get('message') or payload.get('message_zh') or payload.get('code')}")
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries and should_retry_exception(exc, retryable_status_codes):
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            break
    raise RuntimeError(f"request failed after {attempts_made} attempts: {last_error}") from last_error


def request_tikhub(
    workspace: Path,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: Any | None = None,
    timeout_override: int | tuple[int, int] | None = None,
    max_retries_override: int | None = None,
) -> dict[str, Any]:
    config = load_json(workspace / "config.json", {})
    api_key = str(config.get("tikhub_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("missing tikhub_api_key in config.json")
    connect_timeout = int(config.get("connect_timeout_seconds") or 5)
    read_timeout = int(config.get("read_timeout_seconds") or config.get("request_timeout_seconds") or 30)
    timeout = timeout_override or (connect_timeout, read_timeout)
    max_retries = int(max_retries_override or config.get("max_retries") or 3)
    retryable_status_codes = {
        int(value)
        for value in (config.get("retryable_status_codes") or [429, 500, 502, 503, 504])
        if str(value).strip()
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    return request_json(
        method,
        url,
        headers=headers,
        params=params,
        json_body=json_body,
        timeout=timeout,
        max_retries=max_retries,
        session=get_session(),
        retryable_status_codes=retryable_status_codes,
    )


def deep_find_first(node: Any, keys: set[str]) -> Any:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and value not in (None, "", [], {}):
                return value
        for value in node.values():
            found = deep_find_first(value, keys)
            if found not in (None, "", [], {}):
                return found
    elif isinstance(node, list):
        for value in node:
            found = deep_find_first(value, keys)
            if found not in (None, "", [], {}):
                return found
    return None


def deep_collect(node: Any, keys: set[str]) -> list[Any]:
    found: list[Any] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key in keys and value not in (None, "", [], {}):
                found.append(value)
            found.extend(deep_collect(value, keys))
    elif isinstance(node, list):
        for value in node:
            found.extend(deep_collect(value, keys))
    return found


def summarize_counts(value: Any) -> int:
    if value in (None, ""):
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return 0
    suffix_scale = {"k": 1000, "w": 10000, "m": 1000000}
    lowered = text.lower()
    if lowered[-1:] in suffix_scale:
        try:
            return int(float(lowered[:-1]) * suffix_scale[lowered[-1]])
        except ValueError:
            return 0
    try:
        return int(float(lowered))
    except ValueError:
        return 0


def normalize_kuaishou_pcursor(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "e" not in text.lower():
        return text
    try:
        return str(int(Decimal(text)))
    except (InvalidOperation, ValueError):
        return text


def infer_platform_from_text(value: str) -> str:
    lowered = (value or "").lower()
    if "tiktok.com" in lowered:
        return "tiktok"
    if "kuaishou.com" in lowered or "gifshow.com" in lowered:
        return "kuaishou"
    if "@finder" in lowered or "channels.weixin.qq.com" in lowered:
        return "wechat_channels"
    return "douyin"


def find_douyin_sec_user_ids(payload: Any) -> list[str]:
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

    walk(payload)
    return found


def resolve_account_identity(workspace: Path, platform: str, raw_inputs: list[str]) -> dict[str, Any]:
    platform = normalize_platform(platform)
    joined = " ".join(raw_inputs).strip()
    if not joined:
        raise RuntimeError("missing account identifier input")

    if platform in {"douyin", "tiktok"}:
        payload = request_tikhub(workspace, "POST", DOUYIN_SEC_ID_URLS[platform], json_body=raw_inputs)
        sec_user_ids = find_douyin_sec_user_ids(payload)
        if not sec_user_ids:
            raise RuntimeError("No sec_user_id found in TikHub response.")
        return {
            "platform": platform,
            "identity": {
                "sec_user_id": sec_user_ids[0],
            },
            "candidates": sec_user_ids,
        }

    if platform == "kuaishou":
        eid_match = re.search(r"(?:kuaishou\.com/profile|c\.kuaishou\.com/fw/user)/([0-9A-Za-z_-]+)", joined)
        if not eid_match:
            short_url_match = re.search(r"https?://v\.kuaishou\.com/[0-9A-Za-z]+", joined)
            if short_url_match:
                response = requests.get(
                    short_url_match.group(0),
                    allow_redirects=True,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                redirected = response.url
                eid_match = re.search(r"c\.kuaishou\.com/fw/user/([0-9A-Za-z_-]+)", redirected)
        if eid_match:
            eid = eid_match.group(1)
        else:
            generic = re.search(r"\b(?!kuaishou\b)([0-9A-Za-z]{8,})\b", joined)
            if not generic:
                raise RuntimeError("Could not extract kuaishou eid from input.")
            eid = generic.group(1)
        return {
            "platform": platform,
            "identity": {
                "eid": eid,
            },
        }

    username_match = re.search(r"\b([0-9A-Za-z_=-]+@finder)\b", joined)
    if username_match:
        username = username_match.group(1)
        return {
            "platform": platform,
            "identity": {
                "username": username,
            },
        }

    export_id_match = re.search(r"https?://weixin\.qq\.com/sph/([0-9A-Za-z_-]+)", joined)
    if not export_id_match:
        export_id_match = re.search(r"https?://channels\.weixin\.qq\.com/finder-preview/pages/sph\?id=([0-9A-Za-z_-]+)", joined)
    if export_id_match:
        export_id = export_id_match.group(1)
        payload = request_tikhub(
            workspace,
            "GET",
            WECHAT_VIDEO_DETAIL_URL,
            params={"exportId": export_id},
        )
        data = payload.get("data") or {}
        username = str(data.get("username") or "")
        if not username:
            raise RuntimeError(
                f"wechat_channels video detail returned no username for exportId={export_id}"
            )
        return {
            "platform": platform,
            "identity": {"username": username},
            "video_detail": data,
        }

    try:
        search_payload = request_tikhub(
            workspace,
            "GET",
            WECHAT_USER_SEARCH_V2_URL,
            params={"keywords": joined, "page": 0},
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "TikHub wechat_channels user search is currently not returning usable results for this input. "
            "Please provide a direct 视频号 username (xxx@finder) or a share/homepage link."
        ) from exc
    raw_candidates = deep_collect(search_payload.get("data"), {"username", "finder_username"})
    candidates: list[str] = []
    for value in raw_candidates:
        if isinstance(value, str) and value.endswith("@finder") and value not in candidates:
            candidates.append(value)
    if not candidates:
        raise RuntimeError(
            "TikHub wechat_channels search returned no username candidates for this input. "
            "Please provide a direct 视频号 username (xxx@finder) or a share/homepage link."
        )
    return {
        "platform": platform,
        "identity": {"username": candidates[0]},
        "candidates": candidates,
        "search_payload": search_payload,
    }


def unwrap_profile(platform: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if platform in {"douyin", "tiktok"}:
        if isinstance(data, dict):
            for key in ("user", "user_info", "aweme_user_info"):
                value = data.get(key)
                if isinstance(value, dict):
                    return value
            if "uid" in data or "unique_id" in data or "sec_uid" in data:
                return data
        raise RuntimeError("could not find user profile data in TikHub response")

    if platform == "kuaishou":
        profile = (((data or {}).get("userProfile") or {}).get("profile")) or {}
        if profile:
            return data
        raise RuntimeError("could not find kuaishou user profile data in TikHub response")

    if isinstance(data, dict) and data:
        return data
    raise RuntimeError("could not find wechat_channels profile data in TikHub response")


def fetch_profile(workspace: Path, platform: str, identity: dict[str, Any]) -> dict[str, Any]:
    platform = normalize_platform(platform)
    if platform in {"douyin", "tiktok"}:
        payload = request_tikhub(
            workspace,
            "GET",
            PROFILE_URLS[platform],
            params={
                "user_id": identity.get("user_id") or "",
                "sec_user_id": identity.get("sec_user_id") or "",
                "unique_id": identity.get("unique_id") or "",
            },
        )
        return unwrap_profile(platform, payload)

    if platform == "kuaishou":
        payload = request_tikhub(
            workspace,
            "GET",
            PROFILE_URLS[platform],
            params={"user_id": identity.get("eid") or identity.get("user_id") or ""},
            timeout_override=max(35, int(load_json(workspace / "config.json", {}).get("request_timeout_seconds") or 30)),
        )
        return unwrap_profile(platform, payload)

    payload = request_tikhub(
        workspace,
        "POST",
        POSTS_URLS[platform],
        json_body={"username": identity.get("username") or "", "last_buffer": ""},
    )
    return unwrap_profile(platform, payload)


def summarize_profile(platform: str, profile: dict[str, Any], *, identity: dict[str, Any] | None = None) -> dict[str, Any]:
    platform = normalize_platform(platform)
    identity = identity or {}
    if platform in {"douyin", "tiktok"}:
        return {
            "platform": platform,
            "display_name": profile.get("nickname") or profile.get("display_name") or "",
            "identity": {
                "sec_user_id": profile.get("sec_uid") or profile.get("sec_user_id") or identity.get("sec_user_id") or "",
                "user_id": str(profile.get("uid") or profile.get("user_id") or identity.get("user_id") or ""),
                "unique_id": profile.get("unique_id") or identity.get("unique_id") or "",
            },
            "follower_count": summarize_counts(profile.get("follower_count") or profile.get("followers_count")),
            "following_count": summarize_counts(profile.get("following_count")),
            "post_count": summarize_counts(profile.get("aweme_count")),
            "signature": profile.get("signature") or "",
            "region": profile.get("region") or profile.get("account_region") or "",
        }

    if platform == "kuaishou":
        user_profile = profile.get("userProfile") or {}
        profile_block = user_profile.get("profile") or {}
        counts = user_profile.get("ownerCount") or {}
        numeric_user_id = user_profile.get("userDefineId") or user_profile.get("userId") or identity.get("user_id") or ""
        return {
            "platform": platform,
            "display_name": profile_block.get("user_name") or "",
            "identity": {
                "eid": profile_block.get("user_id") or identity.get("eid") or "",
                "user_id": str(numeric_user_id or ""),
                "unique_id": profile_block.get("user_name") or "",
            },
            "follower_count": summarize_counts(counts.get("fan")),
            "following_count": summarize_counts(counts.get("follow")),
            "post_count": summarize_counts(counts.get("photo_public")),
            "signature": profile_block.get("user_text") or "",
            "region": "",
        }

    display_name = str(
        deep_find_first(profile, {"nickname", "nick_name", "name", "username"}) or identity.get("username") or ""
    )
    follower_count = summarize_counts(deep_find_first(profile, {"fans_num", "follower_count", "follow_num"}))
    following_count = summarize_counts(deep_find_first(profile, {"follow_count", "following_count"}))
    post_count = summarize_counts(deep_find_first(profile, {"object_count", "video_count", "feed_count"}))
    signature = str(deep_find_first(profile, {"signature", "desc", "description", "bio"}) or "")
    username = str(deep_find_first(profile, {"username", "finder_username"}) or identity.get("username") or "")
    return {
        "platform": platform,
        "display_name": display_name,
        "identity": {
            "username": username,
        },
        "follower_count": follower_count,
        "following_count": following_count,
        "post_count": post_count,
        "signature": signature,
        "region": "",
    }


def fetch_posts_page(workspace: Path, platform: str, identity: dict[str, Any], cursor: str | int | None) -> dict[str, Any]:
    platform = normalize_platform(platform)
    if platform in {"douyin", "tiktok"}:
        config = load_json(workspace / "config.json", {})
        return request_tikhub(
            workspace,
            "GET",
            POSTS_URLS[platform],
            params={
                "sec_user_id": identity.get("sec_user_id") or "",
                "user_id": identity.get("user_id") or "",
                "unique_id": identity.get("unique_id") or "",
                "max_cursor": cursor or 0,
                "count": int(config.get("page_count") or 20),
                "sort_type": int(config.get("sort_type") or 0),
            },
        )

    if platform == "kuaishou":
        numeric_user_id = str(identity.get("user_id") or "").strip()
        if not numeric_user_id:
            profile = fetch_profile(workspace, platform, identity)
            summary = summarize_profile(platform, profile, identity=identity)
            numeric_user_id = str((summary.get("identity") or {}).get("user_id") or "").strip()
            if numeric_user_id:
                identity["user_id"] = numeric_user_id
        if not numeric_user_id:
            raise RuntimeError(
                "kuaishou app post endpoint requires numeric user_id, but profile lookup did not return one from the current eid"
            )
        config = load_json(workspace / "config.json", {})
        timeout = max(35, int(config.get("request_timeout_seconds") or 30))
        retries = max(5, int(config.get("max_retries") or 3))
        params = {"user_id": numeric_user_id}
        if cursor not in (None, ""):
            params["pcursor"] = normalize_kuaishou_pcursor(cursor)
        try:
            return request_tikhub(
                workspace,
                "GET",
                POSTS_URLS["kuaishou_app_v2"],
                params=params,
                timeout_override=timeout,
                max_retries_override=retries,
            )
        except Exception as exc:
            if cursor in (None, ""):
                try:
                    return request_tikhub(
                        workspace,
                        "GET",
                        POSTS_URLS["kuaishou_hot_post"],
                        params={"user_id": numeric_user_id},
                        timeout_override=timeout,
                        max_retries_override=retries,
                    )
                except Exception:
                    pass
            raise RuntimeError(
                "kuaishou app fetch_user_post_v2 failed after repeated retries "
                f"(user_id={numeric_user_id}, pcursor={cursor!r}). Original error: {exc}"
            ) from exc

    return request_tikhub(
        workspace,
        "POST",
        POSTS_URLS[platform],
        json_body={
            "username": identity.get("username") or "",
            "last_buffer": cursor or "",
        },
    )


def unwrap_posts_page(platform: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | int | None, bool]:
    data = payload.get("data") or {}
    if platform in {"douyin", "tiktok"}:
        if isinstance(data, dict) and isinstance(data.get("aweme_list"), list):
            return data.get("aweme_list") or [], data.get("max_cursor"), bool(data.get("has_more"))
        raise RuntimeError("could not find aweme_list in TikHub response")

    if platform == "kuaishou":
        nested = data.get("visionProfilePhotoList") or {}
        if isinstance(nested, dict) and isinstance(nested.get("feeds"), list):
            next_cursor = normalize_kuaishou_pcursor(nested.get("pcursor"))
            return nested.get("feeds") or [], next_cursor, bool(next_cursor and next_cursor != "no_more")
        if isinstance(data, dict) and isinstance(data.get("feeds"), list):
            next_cursor = normalize_kuaishou_pcursor(data.get("pcursor"))
            has_more = bool(next_cursor)
            return data.get("feeds") or [], next_cursor, has_more
        if data.get("result") == 109:
            raise RuntimeError("kuaishou web feed endpoint returned login_required (result=109)")
        raise RuntimeError("could not find kuaishou feeds in TikHub response")

    if isinstance(data, dict) and isinstance(data.get("object"), list):
        object_list = data.get("object") or []
        next_cursor = ""
        if object_list:
            last_item = object_list[-1] or {}
            next_cursor = str(last_item.get("session_buffer") or last_item.get("last_buffer") or "")
        has_more = bool(next_cursor and next_cursor != str(payload.get("_cursor") or ""))
        return object_list, next_cursor, has_more
    if isinstance(data, dict) and isinstance(data.get("object_list"), list):
        object_list = data.get("object_list") or []
        next_cursor = ""
        if object_list:
            last_item = object_list[-1] or {}
            next_cursor = str(last_item.get("session_buffer") or last_item.get("last_buffer") or "")
        has_more = bool(next_cursor and next_cursor != str(payload.get("_cursor") or ""))
        return object_list, next_cursor, has_more
    raise RuntimeError("could not find wechat_channels object_list in TikHub response")
