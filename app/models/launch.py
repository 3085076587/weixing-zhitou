from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class LaunchAccount(Base, TimestampMixin):
    """计划列表里「全部投放号」下拉的账号。和日期无关，每次同步整表刷新。"""

    __tablename__ = "launch_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class LaunchPlan(Base, TimestampMixin):
    """某一段时间里，计划列表的一行。投放号用下拉框那套名字。"""

    __tablename__ = "launch_plans"
    __table_args__ = (UniqueConstraint("range_start", "range_end", "promotion_id", name="uq_launch_range_plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    range_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    range_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    promotion_id: Mapped[str] = mapped_column(String(80), nullable=False)
    operator_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    group_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    product_name: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    promotion_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    sales: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    roi: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    net_profit: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    net_sales: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    commission: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)


class LaunchSummary(Base, TimestampMixin):
    """投放号计划页右上角那一排汇总，按所选时间整段存一条。"""

    __tablename__ = "launch_summaries"
    __table_args__ = (UniqueConstraint("range_start", "range_end", name="uq_launch_summary"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    range_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    range_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    use_quota: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    order_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    roi: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    wecoin_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)


class LaunchAccountStat(Base, TimestampMixin):
    """投放号计划页左侧每个投放号的消耗、订单、GMV、成交ROI。名字用备注，没有备注再用昵称。"""

    __tablename__ = "launch_account_stats"
    __table_args__ = (UniqueConstraint("range_start", "range_end", "sph_id", name="uq_launch_sph_range"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    range_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    range_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    sph_id: Mapped[str] = mapped_column(String(64), nullable=False)
    nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gmv: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    roi: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)


class LaunchVideoPlan(Base, TimestampMixin):
    """某个时间段里，一条计划详情：被投视频、作者、商品。"""

    __tablename__ = "launch_video_plans"
    __table_args__ = (UniqueConstraint("range_start", "range_end", "plan_id", name="uq_launch_video_plan"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    range_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    range_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    promotion_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    sph_nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="", index=True)
    target_nickname: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    video_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    authors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    products_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    gmv: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    roi: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    detail_ready: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_str: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cost_rate: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    roi_bid: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=0)
    quota: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    no_cost_time: Mapped[str] = mapped_column(String(40), nullable=False, default="")
