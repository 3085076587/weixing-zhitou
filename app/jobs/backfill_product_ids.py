"""按每天的商品列表，把商品 id 补进已有商品记录。

商品名称对得上才写。已经有 id 的不覆盖。

    python -m app.jobs.backfill_product_ids
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from app.db.session import SessionLocal
from app.models.launch import LaunchVideoPlan
from app.services.sync import _catalog_for, apply_catalog_ids

logger = logging.getLogger("zhitou.product_ids")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    db = SessionLocal()
    try:
        first = (
            db.query(LaunchVideoPlan.range_start)
            .filter(LaunchVideoPlan.range_start == LaunchVideoPlan.range_end)
            .order_by(LaunchVideoPlan.range_start.asc())
            .first()
        )
        last = (
            db.query(LaunchVideoPlan.range_start)
            .filter(LaunchVideoPlan.range_start == LaunchVideoPlan.range_end)
            .order_by(LaunchVideoPlan.range_start.desc())
            .first()
        )
        if not first or not last:
            logger.info("没有按天的视频记录")
            return
        day = first[0]
        end = last[0]
        updated = 0
        while day <= end:
            catalog = _catalog_for(day, day)
            rows = (
                db.query(LaunchVideoPlan)
                .filter(LaunchVideoPlan.range_start == day, LaunchVideoPlan.range_end == day)
                .all()
            )
            day_updated = 0
            for row in rows:
                try:
                    products = json.loads(row.products_json or "[]")
                except json.JSONDecodeError:
                    products = []
                if not isinstance(products, list) or not apply_catalog_ids(products, catalog):
                    continue
                row.products_json = json.dumps(products, ensure_ascii=False)
                day_updated += 1
            db.commit()
            updated += day_updated
            logger.info("已处理 %s，补上 %s 条，商品目录 %s 个", day.isoformat(), day_updated, len(catalog))
            day += timedelta(days=1)
        logger.info("写入商品 id %s 条", updated)
    finally:
        db.close()


if __name__ == "__main__":
    main()
