from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.db.session import get_db
from app.services.analytics import build_dashboard, operator_series
from app.services.client import ZhitouError
from app.services.sync import sync_range

router = APIRouter(prefix="/launch", tags=["投放数据"], dependencies=[Depends(get_current_user)])


class SyncBody(BaseModel):
    start: date
    end: date


def _check_range(start: date, end: date) -> None:
    if end < start:
        raise HTTPException(status_code=400, detail="结束日期要晚于开始日期")
    if (end - start).days > 92:
        raise HTTPException(status_code=400, detail="一次最多看 92 天")


@router.get("/dashboard")
def dashboard(
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    today = date.today()
    end = end or today
    start = start or (end - timedelta(days=6))
    _check_range(start, end)
    return build_dashboard(db, start, end)


@router.get("/operator")
def operator(
    name: str,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    today = date.today()
    end = end or today
    start = start or (end - timedelta(days=6))
    _check_range(start, end)
    if not name.strip():
        raise HTTPException(status_code=400, detail="要指定运营")
    return operator_series(db, name.strip(), start, end)


@router.post("/sync")
def sync(body: SyncBody, db: Session = Depends(get_db)) -> dict:
    _check_range(body.start, body.end)
    try:
        return sync_range(db, body.start, body.end)
    except ZhitouError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
