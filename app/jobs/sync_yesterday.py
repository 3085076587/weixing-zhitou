"""每天凌晨 5 点把昨天写入数据库。

写入三样：
- 昨天全部投放号的合计，进 launch_summaries
- 昨天每个投放号的合计，进 launch_account_stats
- 昨天每一条被投视频，以及作者、视频数、商品名称、商品 id、封面，进 launch_video_plans

服务器用 crontab 每天 5:00 执行一次：

    python -m app.jobs.sync_yesterday --once
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

from app.db.session import SessionLocal
from app.jobs.cache_details import _pull
from app.models.launch import LaunchAccountStat, LaunchSummary, LaunchVideoPlan
from app.services.sync import _save_slice, ensure_video_metric_columns, write_plan_detail

logger = logging.getLogger("zhitou.sync_yesterday")


def _next_run(now: datetime | None = None) -> datetime:
    current = now or datetime.now()
    target = current.replace(hour=5, minute=0, second=0, microsecond=0)
    if current >= target:
        target += timedelta(days=1)
    return target


def sync_yesterday(day: date | None = None) -> dict:
    """把某一天（默认昨天）的合计、投放号和每条视频写入数据库。"""
    target = day or (date.today() - timedelta(days=1))
    ensure_video_metric_columns()
    db = SessionLocal()
    try:
        videos = _save_slice(db, target, target, with_videos=True)
        summary = (
            db.query(LaunchSummary)
            .filter(LaunchSummary.range_start == target, LaunchSummary.range_end == target)
            .one_or_none()
        )
        accounts = (
            db.query(LaunchAccountStat)
            .filter(LaunchAccountStat.range_start == target, LaunchAccountStat.range_end == target)
            .count()
        )
        pending = [
            row[0]
            for row in db.query(LaunchVideoPlan.plan_id)
            .filter(
                LaunchVideoPlan.range_start == target,
                LaunchVideoPlan.range_end == target,
                LaunchVideoPlan.detail_ready == 0,
            )
            .distinct()
            .all()
            if row[0]
        ]
        totals = {
            "day": target.isoformat(),
            "cost": float(summary.cost or 0) if summary else 0,
            "gmv": float(summary.order_amount or 0) if summary else 0,
            "orders": int(summary.order_count or 0) if summary else 0,
            "accounts": accounts,
            "videos": videos,
            "details_pending": len(pending),
        }
    finally:
        db.close()
    logger.info(
        "%s 合计已写入：消耗 %s，成交 %s，订单 %s，投放号 %s 个，被投视频 %s 条",
        totals["day"],
        totals["cost"],
        totals["gmv"],
        totals["orders"],
        totals["accounts"],
        totals["videos"],
    )
    saved, missed = _fill_details(pending)
    totals["details_saved"] = saved
    totals["details_missed"] = missed
    logger.info("%s 的视频详情写入 %s 条，没取到 %s 条", target.isoformat(), saved, missed)
    return totals


def _fill_details(plan_ids: list[str]) -> tuple[int, int]:
    if not plan_ids:
        return 0, 0
    from app.core.config import get_settings

    db = SessionLocal()
    saved = 0
    missed = 0
    try:
        for index, plan_id in enumerate(plan_ids, start=1):
            detail = _pull(plan_id)
            if detail is None:
                missed += 1
            else:
                write_plan_detail(db, plan_id, detail)
                saved += 1
                logger.info("详情 %s/%s，计划 %s", index, len(plan_ids), plan_id)
            time.sleep(max(get_settings().detail_cache_pause_seconds, 0.2))
    finally:
        db.close()
    return saved, missed


def serve() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    while True:
        target = _next_run()
        wait = (target - datetime.now()).total_seconds()
        logger.info("下次 %s 写入昨天的合计、每个投放号和每条被投视频", target.strftime("%Y-%m-%d %H:%M"))
        time.sleep(max(wait, 1))
        try:
            sync_yesterday()
        except Exception:
            logger.exception("昨天的数据没写完，明天凌晨 5 点再试")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    if "--once" in sys.argv:
        print(sync_yesterday())
    else:
        serve()
