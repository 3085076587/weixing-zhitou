"""计划详情缓存。只使用 Redis 的 3 号库，避免和别的项目抢库。"""
from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlparse

from app.core.config import get_settings

PREFIX = "zt:detail:"
STATE_KEY = "zt:detail:state"
LOCK_KEY = "zt:detail:lock"
TTL_SECONDS = 48 * 3600
REDIS_DB = 3


def client():
    import redis

    url = urlparse(get_settings().redis_url)
    return redis.Redis(
        host=url.hostname or "127.0.0.1",
        port=url.port or 6379,
        db=REDIS_DB,
        password=url.password,
        decode_responses=True,
        socket_timeout=5,
    )


def compact_from_info(info: dict) -> dict:
    authors: list[str] = []
    products: list[dict] = []
    seen_authors: set[str] = set()
    seen_products: set[str] = set()
    materials = info.get("material_list")
    video_count = 0
    if isinstance(materials, list):
        video_count = len(materials)
        for item in materials:
            if not isinstance(item, dict):
                continue
            account = item.get("account_info") if isinstance(item.get("account_info"), dict) else {}
            author = str(account.get("nickName") or account.get("nickname") or "").strip()
            if author and author not in seen_authors:
                seen_authors.add(author)
                authors.append(author)
            product_id = str(item.get("product_id") or "").strip()
            product_name = str(item.get("finder_wording") or "").strip()
            key = product_id or product_name
            if key and key not in seen_products:
                seen_products.add(key)
                products.append({"id": product_id, "name": product_name or product_id})
    return {
        "authors": authors,
        "products": products,
        "video_count": video_count,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    }


def save_detail(conn, plan_id: str, detail: dict) -> None:
    conn.set(f"{PREFIX}{plan_id}", json.dumps(detail, ensure_ascii=False), ex=TTL_SECONDS)


def read_details(plan_ids: list[str]) -> dict[str, dict | None]:
    ids: list[str] = []
    seen: set[str] = set()
    for plan_id in plan_ids:
        text = str(plan_id or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ids.append(text)
    found: dict[str, dict | None] = {plan_id: None for plan_id in ids}
    if not ids:
        return found
    try:
        conn = client()
        conn.ping()
    except Exception:
        return found
    for start in range(0, len(ids), 200):
        chunk = ids[start : start + 200]
        try:
            raws = conn.mget([f"{PREFIX}{plan_id}" for plan_id in chunk])
        except Exception:
            continue
        for plan_id, raw in zip(chunk, raws):
            if not raw:
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                found[plan_id] = data
    return found


def read_one(conn, plan_id: str) -> dict | None:
    raw = conn.get(f"{PREFIX}{plan_id}")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_state(conn, payload: dict) -> None:
    conn.set(STATE_KEY, json.dumps(payload, ensure_ascii=False))


def acquire_lock(conn, token: str, seconds: int = 120) -> bool:
    return bool(conn.set(LOCK_KEY, token, nx=True, ex=seconds))


def touch_lock(conn, token: str, seconds: int = 120) -> bool:
    if conn.get(LOCK_KEY) != token:
        return False
    conn.expire(LOCK_KEY, seconds)
    return True


def release_lock(conn, token: str) -> None:
    if conn.get(LOCK_KEY) == token:
        conn.delete(LOCK_KEY)
