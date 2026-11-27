import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.launch import LaunchAccountStat, LaunchSummary, LaunchVideoPlan
from app.services.client import fetch_account_stats, fetch_plans, fetch_statistics
from app.services.detail_cache import read_details
from app.services.fields import money


def _account_name(row: dict) -> str:
    remark = str(row.get("remark") or "").strip()
    if remark:
        return remark
    name = str(row.get("nickname") or "").strip()
    return name or "未命名投放号"


def _plan_account_name(row: dict) -> str:
    remark = str(row.get("sph_remark") or "").strip()
    if remark:
        return remark
    name = str(row.get("sph_nickname") or "").strip()
    return name or "未命名投放号"


def _text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _video_detail(plan: dict, info: dict | None) -> dict:
    authors: list[str] = []
    products: list[dict] = []
    seen_authors: set[str] = set()
    seen_products: set[str] = set()
    cached = (
        isinstance(info, dict)
        and isinstance(info.get("authors"), list)
        and "material_list" not in info
    )
    if cached:
        authors = [str(name).strip() for name in info.get("authors") or [] if str(name).strip()]
        for item in info.get("products") or []:
            if not isinstance(item, dict):
                continue
            product_id = _text(item.get("id"), 64)
            product_name = _text(item.get("name"), 255)
            key = product_id or product_name
            if key and key not in seen_products:
                seen_products.add(key)
                products.append({"id": product_id, "name": product_name or product_id})
        video_count = int(info.get("video_count") or plan.get("material_num") or 0)
        materials = None
    else:
        materials = (info or {}).get("material_list") if isinstance(info, dict) else None
    if isinstance(materials, list):
        for item in materials:
            if not isinstance(item, dict):
                continue
            account = item.get("account_info") if isinstance(item.get("account_info"), dict) else {}
            author = _text(account.get("nickName") or account.get("nickname"), 255)
            if author and author not in seen_authors:
                seen_authors.add(author)
                authors.append(author)
            product_id = _text(item.get("product_id"), 64)
            product_name = _text(item.get("finder_wording"), 255)
            key = product_id or product_name
            if key and key not in seen_products:
                seen_products.add(key)
                products.append({"id": product_id, "name": product_name or product_id})
        video_count = len(materials)
    elif not cached:
        video_count = int(plan.get("material_num") or 0)
    if not authors:
        target = _text(plan.get("target_nickname"), 255)
        if target:
            authors.append(target)
    if not products:
        wording = _text(plan.get("finder_wording"), 255)
        if wording:
            products.append({"id": "", "name": wording})
    title = _text(plan.get("finder_description"), 255)
    if not title and authors:
        title = f"{authors[0]}等{len(authors)}人的{video_count}个视频"
    return {
        "authors": authors,
        "products": products,
        "video_count": video_count,
        "title": title,
    }


def _load_videos(start: date, end: date) -> tuple[list[dict], dict[str, dict | None]]:
    plans = fetch_plans(start, end)
    infos = read_details([str(row.get("id") or "") for row in plans])
    return plans, infos


def _save_videos(db: Session, start: date, end: date, plans: list[dict], infos: dict[str, dict | None]) -> int:
    db.query(LaunchVideoPlan).filter(
        LaunchVideoPlan.range_start == start, LaunchVideoPlan.range_end == end
    ).delete(synchronize_session=False)
    seen: set[str] = set()
    saved = 0
    for row in plans:
        plan_id = str(row.get("id") or "").strip()
        if not plan_id or plan_id in seen:
            continue
        seen.add(plan_id)
        detail = _video_detail(row, infos.get(plan_id))
        nickname = _text(_plan_account_name(row), 255)
        db.add(
            LaunchVideoPlan(
                range_start=start,
                range_end=end,
                plan_id=plan_id[:64],
                promotion_id=_text(row.get("promotion_id"), 80),
                sph_nickname=nickname,
                target_nickname=_text(row.get("target_nickname"), 255),
                title=detail["title"],
                video_count=detail["video_count"],
                authors_json=json.dumps(detail["authors"], ensure_ascii=False),
                products_json=json.dumps(detail["products"], ensure_ascii=False),
                cost=money(row.get("cost")),
                order_count=int(row.get("order_num") or 0),
                gmv=money(row.get("order_amount")),
                roi=money(row.get("order_roi") if row.get("order_roi") is not None else row.get("roi")),
                detail_ready=1 if infos.get(plan_id) else 0,
                state_str=_text(row.get("state_str"), 40),
                cost_rate=money(row.get("cost_rate")),
                roi_bid=money(row.get("roi_bid")),
                quota=money(row.get("quota")),
                no_cost_time=_text(row.get("no_cost_time"), 40),
            )
        )
        saved += 1
    return saved


def _save_slice(db: Session, start: date, end: date, with_videos: bool = False) -> int:
    summary = fetch_statistics(start, end)
    accounts = fetch_account_stats(start, end)
    db.query(LaunchSummary).filter(LaunchSummary.range_start == start, LaunchSummary.range_end == end).delete(
        synchronize_session=False
    )
    db.add(
        LaunchSummary(
            range_start=start,
            range_end=end,
            use_quota=money(summary.get("use_quota")),
            cost=money(summary.get("cost")),
            order_amount=money(summary.get("order_amount")),
            order_count=int(summary.get("order_num") or 0),
            roi=money(summary.get("roi")),
            wecoin_cost=money(summary.get("wecoin_cost")),
        )
    )
    db.query(LaunchAccountStat).filter(
        LaunchAccountStat.range_start == start, LaunchAccountStat.range_end == end
    ).delete(synchronize_session=False)
    seen: set[str] = set()
    saved = 0
    for index, row in enumerate(accounts):
        sph_id = str(row.get("id") or "").strip() or f"missing-{index}"
        if sph_id in seen:
            continue
        seen.add(sph_id)
        db.add(
            LaunchAccountStat(
                range_start=start,
                range_end=end,
                sph_id=sph_id[:64],
                nickname=_account_name(row)[:255],
                cost=money(row.get("cost")),
                order_count=int(row.get("order_num") or 0),
                gmv=money(row.get("order_amount")),
                roi=money(row.get("roi")),
            )
        )
        saved += 1
    db.commit()
    if not with_videos:
        return saved
    plans, infos = _load_videos(start, end)
    videos = _save_videos(db, start, end, plans, infos)
    db.commit()
    return videos or saved


def ensure_video_metric_columns() -> None:
    """旧表补上每条被投视频当天的消耗、订单、GMV、成交ROI。"""
    from sqlalchemy import inspect, text

    from app.db.session import engine

    insp = inspect(engine)
    if "launch_video_plans" not in insp.get_table_names():
        return
    cols = {column["name"] for column in insp.get_columns("launch_video_plans")}
    statements = []
    if "cost" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN cost NUMERIC(14,2) NOT NULL DEFAULT 0")
    if "order_count" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN order_count INT NOT NULL DEFAULT 0")
    if "gmv" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN gmv NUMERIC(14,2) NOT NULL DEFAULT 0")
    if "roi" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN roi NUMERIC(12,4) NOT NULL DEFAULT 0")
    if "detail_ready" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN detail_ready INT NOT NULL DEFAULT 0")
    if "state_str" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN state_str VARCHAR(40) NOT NULL DEFAULT ''")
    if "cost_rate" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN cost_rate NUMERIC(8,2) NOT NULL DEFAULT 0")
    if "roi_bid" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN roi_bid NUMERIC(12,4) NOT NULL DEFAULT 0")
    if "quota" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN quota NUMERIC(14,2) NOT NULL DEFAULT 0")
    if "no_cost_time" not in cols:
        statements.append("ALTER TABLE launch_video_plans ADD COLUMN no_cost_time VARCHAR(40) NOT NULL DEFAULT ''")
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))


def write_plan_detail(db: Session, plan_id: str, detail: dict) -> int:
    """一条详情写进这个视频在每一天的数据库记录。"""
    rows = db.query(LaunchVideoPlan).filter(LaunchVideoPlan.plan_id == plan_id).all()
    authors = [str(name).strip() for name in detail.get("authors") or [] if str(name).strip()]
    products = [
        {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
        for item in detail.get("products") or []
        if isinstance(item, dict) and (item.get("id") or item.get("name"))
    ]
    video_count = int(detail.get("video_count") or 0)
    for row in rows:
        if authors:
            row.authors_json = json.dumps(authors, ensure_ascii=False)
        if products:
            row.products_json = json.dumps(products, ensure_ascii=False)
        if video_count:
            row.video_count = video_count
        row.detail_ready = 1
    db.commit()
    return len(rows)


def apply_cached_details(db: Session) -> int:
    """把 Redis 里的作者、视频数、商品写回每一天的被投视频。"""
    from app.services.detail_cache import read_details

    rows = db.query(LaunchVideoPlan).all()
    infos = read_details([row.plan_id for row in rows])
    updated = 0
    for row in rows:
        info = infos.get(row.plan_id)
        if not info:
            continue
        authors = [str(name).strip() for name in info.get("authors") or [] if str(name).strip()]
        products = [
            {"id": str(item.get("id") or ""), "name": str(item.get("name") or "")}
            for item in info.get("products") or []
            if isinstance(item, dict) and (item.get("id") or item.get("name"))
        ]
        if authors:
            row.authors_json = json.dumps(authors, ensure_ascii=False)
        if products:
            row.products_json = json.dumps(products, ensure_ascii=False)
        cached_count = int(info.get("video_count") or 0)
        if cached_count:
            row.video_count = cached_count
        row.detail_ready = 1
        updated += 1
    db.commit()
    return updated


def sync_range(db: Session, start: date, end: date) -> dict:
    if end < start:
        raise ValueError("结束日期要晚于开始日期")
    if (end - start).days > 92:
        raise ValueError("一次最多同步 92 天")
    ensure_video_metric_columns()
    videos = 0
    day = start
    while day <= end:
        videos += _save_slice(db, day, day, with_videos=True)
        day += timedelta(days=1)
    if start != end and (end - start).days <= 30:
        videos += _save_slice(db, start, end, with_videos=True)
    return {"start": start.isoformat(), "end": end.isoformat(), "plans": videos, "accounts": videos}
