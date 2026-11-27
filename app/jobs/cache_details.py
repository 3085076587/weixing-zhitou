"""定时把今天的计划详情一条一条写入 Redis 3 号库。

10 月 1 日到昨天的数据在数据库里，页面只读库。这个任务只缓存今天。
单独运行：

    D:\\fastapi-project\\zhitou\\.venv\\Scripts\\python.exe -m app.jobs.cache_details
"""
from __future__ import annotations

import logging
import time
import uuid
from datetime import date, datetime, timedelta

from app.core.config import get_settings
from app.services.client import RateLimited, ZhitouError, fetch_order_info, fetch_plans
from app.services.detail_cache import (
    LOCK_KEY,
    acquire_lock,
    client,
    compact_from_info,
    read_one,
    release_lock,
    save_detail,
    touch_lock,
    write_state,
)

logger = logging.getLogger("zhitou.detail_cache")


def _fresh(detail: dict | None, interval_minutes: int) -> bool:
    if not detail:
        return False
    text = str(detail.get("fetched_at") or "")
    try:
        fetched = datetime.fromisoformat(text)
    except ValueError:
        return False
    return datetime.now() - fetched < timedelta(minutes=interval_minutes)


def run_once() -> dict:
    settings = get_settings()
    start = end = date.today()
    ids: list[str] = []
    seen: set[str] = set()
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=29))
        for row in fetch_plans(cursor, chunk_end):
            plan_id = str(row.get("id") or "").strip()
            if not plan_id or plan_id in seen:
                continue
            seen.add(plan_id)
            ids.append(plan_id)
        cursor = chunk_end + timedelta(days=1)
    conn = client()
    token = uuid.uuid4().hex
    if not acquire_lock(conn, token):
        logger.info("详情缓存已有一轮在跑，这一轮跳过")
        return {"skipped": True}
    saved = 0
    skipped = 0
    missed = 0
    try:
        write_state(
            conn,
            {
                "status": "running",
                "start": start.isoformat(),
                "end": end.isoformat(),
                "total": len(ids),
                "saved": 0,
                "started_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        for index, plan_id in enumerate(ids, start=1):
            if not touch_lock(conn, token):
                logger.warning("详情缓存锁已丢失，停止本轮")
                break
            if _fresh(read_one(conn, plan_id), settings.detail_cache_interval_minutes):
                skipped += 1
                continue
            detail = _pull(plan_id)
            if detail is None:
                missed += 1
            else:
                save_detail(conn, plan_id, detail)
                saved += 1
            if index % 50 == 0:
                logger.info("详情缓存 %s/%s，新写入 %s，跳过 %s", index, len(ids), saved, skipped)
            time.sleep(max(settings.detail_cache_pause_seconds, 0.2))
        payload = {
            "status": "done",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total": len(ids),
            "saved": saved,
            "skipped": skipped,
            "missed": missed,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
        }
        write_state(conn, payload)
        logger.info("详情缓存写完：扫描 %s，新写入 %s，未变化 %s，没取到 %s", len(ids), saved, skipped, missed)
        return payload
    finally:
        release_lock(conn, token)


def _pull(plan_id: str) -> dict | None:
    for attempt in range(5):
        try:
            info = fetch_order_info(plan_id)
        except RateLimited:
            time.sleep(2 + attempt)
            continue
        except ZhitouError as exc:
            if "登录" in str(exc):
                raise
            logger.warning("计划 %s 的详情没取到：%s", plan_id, exc)
            return None
        return compact_from_info(info)
    logger.warning("计划 %s 连续限流，先跳过", plan_id)
    return None


def fill_stored_details() -> dict:
    """把还没写进数据库的详情逐条取回，立刻写到每一天的记录上。"""
    from app.db.session import SessionLocal
    from app.models.launch import LaunchVideoPlan
    from app.services.sync import apply_cached_details, ensure_video_metric_columns, write_plan_detail

    ensure_video_metric_columns()
    db = SessionLocal()
    try:
        already = apply_cached_details(db)
        if already:
            logger.info("已有详情写入数据库 %s 条", already)
        pending = [
            row[0]
            for row in db.query(LaunchVideoPlan.plan_id)
            .filter(LaunchVideoPlan.detail_ready == 0)
            .distinct()
            .all()
            if row[0]
        ]
    finally:
        db.close()
    logger.info("还有 %s 条详情没写入数据库", len(pending))
    if not pending:
        return {"saved": 0, "missed": 0, "updated": already}
    conn = client()
    token = uuid.uuid4().hex
    if not acquire_lock(conn, token):
        release_lock(conn, conn.get(LOCK_KEY) or "")
        if not acquire_lock(conn, token):
            conn.delete(LOCK_KEY)
            acquire_lock(conn, token)
    saved = 0
    missed = 0
    db = SessionLocal()
    try:
        for index, plan_id in enumerate(pending, start=1):
            touch_lock(conn, token)
            detail = _pull(plan_id)
            if detail is None:
                missed += 1
            else:
                try:
                    save_detail(conn, plan_id, detail)
                except Exception:
                    logger.warning("计划 %s 的详情已写入数据库，缓存副本没记下", plan_id)
                rows = write_plan_detail(db, plan_id, detail)
                saved += 1
                logger.info("已写入数据库 %s/%s，计划 %s，覆盖 %s 天", index, len(pending), plan_id, rows)
            if index % 50 == 0:
                logger.info("进度 %s/%s，写入数据库 %s，没取到 %s", index, len(pending), saved, missed)
            time.sleep(max(get_settings().detail_cache_pause_seconds, 0.2))
    finally:
        db.close()
        release_lock(conn, token)
    logger.info("详情补完，写入数据库 %s 条，没取到 %s 条", saved, missed)
    return {"saved": saved, "missed": missed, "updated": already}


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    while True:
        settings = get_settings()
        wait = max(settings.detail_cache_interval_minutes, 1) * 60
        try:
            client().ping()
        except Exception:
            logger.exception("Redis 3 号库连不上，1 分钟后重试")
            time.sleep(60)
            continue
        started = time.monotonic()
        try:
            run_once()
        except Exception:
            logger.exception("详情缓存这一轮失败，下一轮再试")
        spent = time.monotonic() - started
        time.sleep(max(30.0, wait - spent))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    print(fill_stored_details())
