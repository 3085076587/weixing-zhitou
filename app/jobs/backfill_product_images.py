"""把每天计划列表里的视频封面写进已有商品记录。

封面就是投放后台这条商品视频的图片。商品列表接口本身不返回图片。

    python -m app.jobs.backfill_product_images
"""
from __future__ import annotations

import json
import logging
from datetime import timedelta

from app.db.session import SessionLocal
from app.models.launch import LaunchVideoPlan
from app.services.client import fetch_plans

logger = logging.getLogger("zhitou.product_images")


def _attach(products: list, wording: str, cover: str) -> bool:
    if not cover:
        return False
    if not products and wording:
        products.append({"id": "", "name": wording, "image": cover})
        return True
    changed = False
    for item in products:
        if not isinstance(item, dict) or item.get("image"):
            continue
        name = str(item.get("name") or "").strip()
        if name == wording or len(products) == 1:
            item["image"] = cover
            changed = True
    return changed


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
            plans = fetch_plans(day, day)
            for plan in plans:
                cover = str(plan.get("finder_cover_url") or "").strip()
                wording = str(plan.get("finder_wording") or "").strip()
                plan_id = str(plan.get("id") or "")
                if not cover or not plan_id:
                    continue
                row = (
                    db.query(LaunchVideoPlan)
                    .filter(
                        LaunchVideoPlan.plan_id == plan_id,
                        LaunchVideoPlan.range_start == day,
                        LaunchVideoPlan.range_end == day,
                    )
                    .one_or_none()
                )
                if row is None:
                    continue
                try:
                    products = json.loads(row.products_json or "[]")
                except json.JSONDecodeError:
                    products = []
                if not isinstance(products, list):
                    products = []
                if not _attach(products, wording, cover):
                    continue
                row.products_json = json.dumps(products, ensure_ascii=False)
                updated += 1
            db.commit()
            logger.info("已处理 %s", day.isoformat())
            day += timedelta(days=1)
        logger.info("写入封面 %s 条", updated)
    finally:
        db.close()


if __name__ == "__main__":
    main()
