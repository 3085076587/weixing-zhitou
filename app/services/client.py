from datetime import date, datetime, time

import httpx

from app.core.config import get_settings


class ZhitouError(RuntimeError):
    pass


def _day_bounds(day: date) -> tuple[str, str]:
    start = datetime.combine(day, time.min).strftime("%Y-%m-%d %H:%M:%S")
    end = datetime.combine(day, time.max.replace(microsecond=0)).strftime("%Y-%m-%d %H:%M:%S")
    return start, end


def _headers() -> dict:
    settings = get_settings()
    token = (settings.zhitou_token or "").strip()
    if not token:
        raise ZhitouError("还没有投放后台的登录令牌")
    if not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    return {
        "authorization": token,
        "accept": "application/json, text/plain, */*",
        "origin": "https://www.ieh5.com",
        "referer": "https://www.ieh5.com/",
    }


def _post(path: str, payload: dict) -> dict:
    import time

    settings = get_settings()
    last_message = "投放数据拉取失败"
    for attempt in range(6):
        with httpx.Client(timeout=40) as client:
            try:
                response = client.post(
                    f"{settings.zhitou_api_base.rstrip('/')}{path}",
                    headers=_headers(),
                    json=payload,
                )
            except httpx.HTTPError:
                time.sleep(1 + attempt)
                continue
        if response.status_code == 429:
            time.sleep(1.5 * (attempt + 1))
            continue
        if response.status_code in (401, 403):
            raise ZhitouError("登录已失效，需要重新保存投放后台的登录令牌")
        try:
            body = response.json()
        except ValueError as exc:
            raise ZhitouError("投放数据返回的不是 JSON") from exc
        if body.get("code") in (10429,) or "限流" in str(body.get("msg") or ""):
            time.sleep(1.5 * (attempt + 1))
            continue
        if body.get("code") != 0:
            message = str(body.get("msg") or "投放数据拉取失败")
            last_message = message
            if "登录" in message or "token" in message.lower() or "auth" in message.lower():
                raise ZhitouError("登录已失效，需要重新保存投放后台的登录令牌")
            raise ZhitouError(message)
        data = body.get("data") or {}
        return data if isinstance(data, dict) else {}
    raise ZhitouError(last_message)


def _paged(path: str, payload: dict, limit: int, max_pages: int = 50) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while page <= max_pages:
        body = dict(payload)
        body["page"] = page
        body["limit"] = limit
        data = _post(path, body)
        batch = data.get("data") or []
        rows.extend(item for item in batch if isinstance(item, dict))
        last_page = int(data.get("last_page") or 1)
        if page >= last_page or not batch:
            break
        page += 1
    return rows


def fetch_statistics(start: date, end: date) -> dict:
    """投放号计划右上角六张卡片。"""
    start_text, _ = _day_bounds(start)
    _, end_text = _day_bounds(end)
    return _post(
        "/order/statistics",
        {
            "promotion_id": "",
            "state": "",
            "sph_ids": [],
            "author_usernames": [],
            "product_id": "",
            "department_id": "",
            "operate_id": "",
            "start_time": start_text,
            "end_time": end_text,
            "time_type": 2,
            "platform_type": "",
        },
    )


def fetch_account_stats(start: date, end: date) -> list[dict]:
    """投放号计划左侧每个投放号。"""
    start_text, _ = _day_bounds(start)
    _, end_text = _day_bounds(end)
    return _paged(
        "/order/shipinhao_lists",
        {
            "time_type": 2,
            "start_time": start_text,
            "end_time": end_text,
            "shipinhao_nickname": "",
            "promotion_order": "",
            "sph_ids": [],
            "platform_type": "",
        },
        100,
    )


def fetch_product_catalog(start: date, end: date) -> dict[str, str]:
    """这一天的商品名称对应商品 id。计划列表本身不带商品 id。"""
    start_text, _ = _day_bounds(start)
    _, end_text = _day_bounds(end)
    rows = _paged(
        "/product/lists",
        {
            "time_type": 2,
            "start_time": start_text,
            "end_time": end_text,
            "platform_type": "",
        },
        100,
    )
    catalog: dict[str, str] = {}
    for row in rows:
        name = str(row.get("product_name") or "").strip()
        product_id = str(row.get("product_id") or "").strip()
        if name and product_id:
            catalog.setdefault(name, product_id)
    return catalog


def fetch_plans(start: date, end: date) -> list[dict]:
    """按页面上的时间范围拉计划列表。"""
    start_text, _ = _day_bounds(start)
    _, end_text = _day_bounds(end)
    return _paged(
        "/order/lists",
        {
            "platform": 1,
            "version": 1,
            "promotion_id": "",
            "state": "",
            "time_type": 2,
            "sph_ids": [],
            "order": "",
            "author_usernames": [],
            "product_id": "",
            "department_id": "",
            "operate_id": "",
            "start_time": start_text,
            "end_time": end_text,
            "export_id": "",
            "group_id": "",
            "target": "",
            "is_lever": "",
            "lever_id": None,
            "billing_method": "",
            "currency_choice": "",
            "classification": "",
            "platform_type": "",
        },
        100,
        120,
    )


class RateLimited(ZhitouError):
    """投放详情接口返回了限流。调用方放慢后再试，不要并发重打。"""


def fetch_order_info(plan_id: str) -> dict:
    """一条计划详情。给定时脚本逐条调用，页面请求不要用它。"""
    settings = get_settings()
    with httpx.Client(timeout=30, headers=_headers()) as client:
        try:
            response = client.get(
                f"{settings.zhitou_api_base.rstrip('/')}/order/info",
                params={"id": plan_id},
            )
        except httpx.HTTPError as exc:
            raise ZhitouError("投放详情请求失败") from exc
    if response.status_code == 429:
        raise RateLimited("服务限流，请稍后再试")
    if response.status_code in (401, 403):
        raise ZhitouError("登录已失效，需要重新保存投放后台的登录令牌")
    try:
        body = response.json()
    except ValueError as exc:
        raise ZhitouError("投放详情返回的不是 JSON") from exc
    if body.get("code") in (10429,) or "限流" in str(body.get("msg") or ""):
        raise RateLimited("服务限流，请稍后再试")
    if body.get("code") != 0:
        message = str(body.get("msg") or "投放详情拉取失败")
        if "登录" in message or "token" in message.lower() or "auth" in message.lower():
            raise ZhitouError("登录已失效，需要重新保存投放后台的登录令牌")
        raise ZhitouError(message)
    data = body.get("data") or {}
    if not isinstance(data, dict):
        raise ZhitouError("投放详情没有返回计划内容")
    return data
