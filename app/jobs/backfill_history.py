"""从 2026-10-01 起，按天把投放号、被投视频和详情写入数据库。

    D:\\fastapi-project\\zhitou\\.venv\\Scripts\\python.exe -m app.jobs.backfill_history
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from app.db.session import SessionLocal
from app.services.sync import _save_slice, apply_cached_details, ensure_video_metric_columns

logger = logging.getLogger("zhitou.backfill")
START = date(2026, 10, 1)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    ensure_video_metric_columns()
    end = date.today()
    db = SessionLocal()
    try:
        day = START
        while day <= end:
            saved = _save_slice(db, day, day, with_videos=True)
            logger.info("已写入 %s，被投视频 %s 条", day.isoformat(), saved)
            day += timedelta(days=1)
        if START != end:
            saved = _save_slice(db, START, end, with_videos=True)
            logger.info("已写入 %s 至 %s 整段，被投视频 %s 条", START.isoformat(), end.isoformat(), saved)
        updated = apply_cached_details(db)
        logger.info("详情缓存写回 %s 条", updated)
    finally:
        db.close()


if __name__ == "__main__":
    main()
