import re
from decimal import Decimal, InvalidOperation

_PRODUCT = re.compile(r"【([^】]+)】")
_CENT = Decimal("0.01")


def money(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value)).quantize(_CENT)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def commission_amount(sales: Decimal, rate) -> Decimal:
    """佣金率大于 1 时按百分数，否则按小数。页面上的 100 表示 100%。"""
    ratio = money(rate)
    if ratio > 1:
        ratio = ratio / Decimal(100)
    return (sales * ratio).quantize(_CENT)


def operator_name(row: dict) -> str:
    """和计划列表「全部投放号」下拉一致：有备注就显示 备注(昵称)，否则只显示昵称。"""
    if "sph_remark" in row or "sph_nickname" in row:
        remark = str(row.get("sph_remark") or "").strip()
        nickname = str(row.get("sph_nickname") or "").strip()
    else:
        remark = str(row.get("remark") or "").strip()
        nickname = str(row.get("nickname") or "").strip()
    if remark:
        return f"{remark}({nickname})"
    return nickname or "未命名投放号"


def product_name(row: dict) -> str:
    info = row.get("project_info")
    if isinstance(info, list):
        for item in info:
            if not isinstance(item, dict):
                continue
            for key in ("product_name", "goods_name", "name", "title"):
                text = str(item.get(key) or "").strip()
                if text:
                    return text
    nickname = str(row.get("sph_nickname") or "")
    found = _PRODUCT.findall(nickname)
    if found:
        return found[-1].strip() or "未分品"
    nickname = nickname.strip()
    return nickname or "未分品"
