import json
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.launch import LaunchAccountStat, LaunchSummary, LaunchVideoPlan


def _num(value) -> float:
    if value is None:
        return 0.0
    return round(float(value), 2)


def _cards(row: LaunchSummary | None) -> dict:
    if row is None:
        return {
            "use_quota": 0,
            "cost": 0,
            "order_amount": 0,
            "order_count": 0,
            "roi": 0,
            "wecoin_cost": 0,
            "account_count": 0,
        }
    return {
        "use_quota": _num(row.use_quota),
        "cost": _num(row.cost),
        "order_amount": _num(row.order_amount),
        "order_count": int(row.order_count or 0),
        "roi": _num(row.roi),
        "wecoin_cost": _num(row.wecoin_cost),
    }


def _product_key(product: dict) -> str:
    name = str(product.get("name") or "").strip()
    product_id = str(product.get("id") or "").strip()
    return name or product_id


def _videos(db: Session, start: date, end: date) -> tuple[dict[str, dict], int, int]:
    """一段时间里每个投放号一行：作者、商品、视频都按整段去重。"""
    rows = (
        db.query(LaunchVideoPlan)
        .filter(
            LaunchVideoPlan.range_start == LaunchVideoPlan.range_end,
            LaunchVideoPlan.range_start >= start,
            LaunchVideoPlan.range_end <= end,
        )
        .all()
    )
    if not rows:
        rows = (
            db.query(LaunchVideoPlan)
            .filter(LaunchVideoPlan.range_start == start, LaunchVideoPlan.range_end == end)
            .all()
        )
    grouped: dict[str, dict] = {}
    all_products: set[str] = set()
    for row in rows:
        name = row.sph_nickname or "未命名投放号"
        bucket = grouped.setdefault(
            name,
            {"authors": [], "seen_authors": set(), "products": {}, "plans": {}},
        )
        try:
            authors = json.loads(row.authors_json or "[]")
        except json.JSONDecodeError:
            authors = []
        try:
            products = json.loads(row.products_json or "[]")
        except json.JSONDecodeError:
            products = []
        if isinstance(authors, list):
            for author in authors:
                text = str(author).strip()
                if text and text not in bucket["seen_authors"]:
                    bucket["seen_authors"].add(text)
                    bucket["authors"].append(text)
        if isinstance(products, list):
            day = row.range_start.isoformat()
            for item in products:
                if not isinstance(item, dict):
                    continue
                key = _product_key(item)
                if not key:
                    continue
                all_products.add(key)
                name_text = str(item.get("name") or "").strip() or key
                product_id = str(item.get("id") or "").strip()
                image = str(item.get("image") or "").strip()
                slot = bucket["products"].get(key)
                if slot is None:
                    slot = {"id": product_id, "name": name_text, "image": image, "days": []}
                    bucket["products"][key] = slot
                else:
                    if product_id and not slot["id"]:
                        slot["id"] = product_id
                    if name_text and (not slot["name"] or slot["name"] == slot["id"]):
                        slot["name"] = name_text
                    if image and not slot["image"]:
                        slot["image"] = image
                if day not in slot["days"]:
                    slot["days"].append(day)
        plan_id = str(row.plan_id or "")
        count = int(row.video_count or 0)
        bucket["plans"][plan_id] = max(bucket["plans"].get(plan_id, 0), count)
    summary = {
        name: {
            "authors": bucket["authors"],
            "author_count": len(bucket["authors"]),
            "video_count": sum(bucket["plans"].values()),
            "product_count": len(bucket["products"]),
            "products": sorted(
                ({**item, "days": sorted(item["days"])} for item in bucket["products"].values()),
                key=lambda item: item["name"],
            ),
        }
        for name, bucket in grouped.items()
    }
    return summary, len(all_products), sum(item["video_count"] for item in summary.values())


def _account(row: LaunchAccountStat) -> dict:
    return {
        "name": row.nickname,
        "cost": _num(row.cost),
        "order_count": int(row.order_count or 0),
        "gmv": _num(row.gmv),
        "roi": _num(row.roi),
    }


def build_dashboard(db: Session, start: date, end: date) -> dict:
    # 跨天一律把每一天相加。只有查单独一天时才用那一天自己的记录。
    summary = None
    account_rows: list[LaunchAccountStat] = []
    if start == end:
        summary = (
            db.query(LaunchSummary)
            .filter(LaunchSummary.range_start == start, LaunchSummary.range_end == end)
            .one_or_none()
        )
        account_rows = (
            db.query(LaunchAccountStat)
            .filter(LaunchAccountStat.range_start == start, LaunchAccountStat.range_end == end)
            .all()
        )
    daily_rows = (
        db.query(LaunchSummary)
        .filter(
            LaunchSummary.range_start == LaunchSummary.range_end,
            LaunchSummary.range_start >= start,
            LaunchSummary.range_end <= end,
        )
        .all()
    )
    if account_rows:
        operators = [_account(row) for row in account_rows]
    else:
        grouped: dict[str, dict] = {}
        daily_accounts = (
            db.query(LaunchAccountStat)
            .filter(
                LaunchAccountStat.range_start == LaunchAccountStat.range_end,
                LaunchAccountStat.range_start >= start,
                LaunchAccountStat.range_end <= end,
            )
            .all()
        )
        for row in daily_accounts:
            bucket = grouped.setdefault(
                row.nickname, {"name": row.nickname, "cost": 0.0, "order_count": 0, "gmv": 0.0}
            )
            bucket["cost"] += float(row.cost or 0)
            bucket["order_count"] += int(row.order_count or 0)
            bucket["gmv"] += float(row.gmv or 0)
        operators = []
        for bucket in grouped.values():
            cost = bucket["cost"]
            operators.append(
                {
                    "name": bucket["name"],
                    "cost": round(cost, 2),
                    "order_count": bucket["order_count"],
                    "gmv": round(bucket["gmv"], 2),
                    "roi": round(bucket["gmv"] / cost, 2) if cost else 0,
                }
            )
    video_map, product_count, video_count = _videos(db, start, end)
    for item in operators:
        extra = video_map.get(item["name"], {})
        item["authors"] = extra.get("authors", [])
        item["author_count"] = extra.get("author_count", 0)
        item["video_count"] = extra.get("video_count", 0)
        item["product_count"] = extra.get("product_count", 0)
        item["products"] = extra.get("products", [])
    if summary is None and daily_rows:
        cost = float(sum(row.cost or 0 for row in daily_rows))
        order_amount = float(sum(row.order_amount or 0 for row in daily_rows))
        latest = max(daily_rows, key=lambda row: row.range_start)
        overview = {
            "use_quota": _num(latest.use_quota),
            "cost": _num(cost),
            "order_amount": _num(order_amount),
            "order_count": int(sum(row.order_count or 0 for row in daily_rows)),
            "roi": round(order_amount / cost, 2) if cost else 0,
            "wecoin_cost": _num(sum(row.wecoin_cost or 0 for row in daily_rows)),
            "account_count": 0,
        }
    else:
        overview = _cards(summary)
    overview["account_count"] = len(operators)
    overview["product_count"] = product_count
    overview["video_count"] = video_count

    by_day = {row.range_start: row for row in daily_rows}
    count_rows = (
        db.query(LaunchAccountStat.range_start)
        .filter(
            LaunchAccountStat.range_start == LaunchAccountStat.range_end,
            LaunchAccountStat.range_start >= start,
            LaunchAccountStat.range_end <= end,
        )
        .all()
    )
    counts: dict[date, int] = {}
    for (day,) in count_rows:
        counts[day] = counts.get(day, 0) + 1

    trend = []
    cursor = start
    while cursor <= end:
        point = {"date": cursor.isoformat()}
        point.update(_cards(by_day.get(cursor)))
        point["account_count"] = counts.get(cursor, 0)
        trend.append(point)
        cursor += timedelta(days=1)

    def ranked(key: str) -> list[dict]:
        ordered = sorted(operators, key=lambda item: item[key], reverse=True)
        return [{**item, "rank": index} for index, item in enumerate(ordered, start=1)]

    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "overview": overview,
        "operators": ranked("cost"),
        "rank_cost": ranked("cost"),
        "rank_gmv": ranked("gmv"),
        "video_days": [],
        "trend": trend,
    }


def operator_series(db: Session, name: str, start: date, end: date) -> dict:
    ranged = []
    if start == end:
        ranged = (
            db.query(LaunchAccountStat)
            .filter(
                LaunchAccountStat.nickname == name,
                LaunchAccountStat.range_start == start,
                LaunchAccountStat.range_end == end,
            )
            .all()
        )
    daily = (
        db.query(LaunchAccountStat)
        .filter(
            LaunchAccountStat.nickname == name,
            LaunchAccountStat.range_start == LaunchAccountStat.range_end,
            LaunchAccountStat.range_start >= start,
            LaunchAccountStat.range_end <= end,
        )
        .order_by(LaunchAccountStat.range_start)
        .all()
    )
    source = ranged or daily
    overview = {
        "cost": _num(sum(row.cost or 0 for row in source)),
        "order_count": int(sum(row.order_count or 0 for row in source)),
        "gmv": _num(sum(row.gmv or 0 for row in source)),
        "roi": _num(source[0].roi) if len(source) == 1 else 0,
    }
    if len(source) > 1 and overview["cost"]:
        overview["roi"] = round(overview["gmv"] / overview["cost"], 2)
    by_day = {row.range_start: row for row in daily}
    trend = []
    cursor = start
    while cursor <= end:
        row = by_day.get(cursor)
        trend.append(
            {
                "date": cursor.isoformat(),
                "cost": _num(row.cost) if row else 0,
                "gmv": _num(row.gmv) if row else 0,
                "order_count": int(row.order_count or 0) if row else 0,
                "roi": _num(row.roi) if row else 0,
            }
        )
        cursor += timedelta(days=1)
    return {
        "name": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "overview": overview,
        "trend": trend,
    }
