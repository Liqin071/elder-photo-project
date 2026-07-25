"""时间线 API"""
from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import func, extract
from typing import Optional
from datetime import datetime

from models.database import SessionLocal
from models.photo import Photo
from models.elderly import Elderly
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["时间线"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_uid(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    uid = verify_token(authorization.split(" ")[1])
    if not uid:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    return uid


@router.get("/timeline/years")
def timeline_years(
    elder_id: Optional[int] = Query(None, alias="elderId"),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    q = db.query(
        func.year(Photo.upload_time).label("year"),
        func.count(Photo.id).label("cnt")
    )
    if elder_id:
        q = q.filter(Photo.elderly_id == elder_id)
    rows = q.group_by(func.year(Photo.upload_time)).order_by(
        func.year(Photo.upload_time).desc()
    ).all()
    years = []
    for r in rows:
        cover = db.query(Photo).filter(
            func.year(Photo.upload_time) == r.year
        )
        if elder_id:
            cover = cover.filter(Photo.elderly_id == elder_id)
        cover = cover.order_by(Photo.upload_time.asc()).first()
        years.append({
            "year": r.year,
            "count": r.cnt,
            "coverUrl": f"/uploads/{cover.original_path}" if cover else None
        })
    return {"years": years}


@router.get("/timeline/aggregation")
def timeline_aggregation(
    elder_id: Optional[int] = Query(None, alias="elderId"),
    year: int = Query(...),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    months = []
    for m in range(1, 13):
        q = db.query(Photo).filter(
            func.year(Photo.upload_time) == year,
            func.month(Photo.upload_time) == m
        )
        if elder_id:
            q = q.filter(Photo.elderly_id == elder_id)
        cnt = q.count()
        if cnt == 0:
            continue
        first = q.order_by(Photo.upload_time.asc()).first()
        last = q.order_by(Photo.upload_time.desc()).first()
        months.append({
            "month": m,
            "count": cnt,
            "coverUrl": f"/uploads/{first.original_path}" if first else None,
            "firstDate": str(first.upload_time.date()) if first else None,
            "lastDate": str(last.upload_time.date()) if last else None
        })
    return {"year": year, "months": months}


@router.get("/timeline")
def timeline(
    elder_id: Optional[int] = Query(None, alias="elderId"),
    start_date: Optional[str] = Query(None, alias="startDate"),
    end_date: Optional[str] = Query(None, alias="endDate"),
    cursor: Optional[int] = None,
    page_size: int = Query(20, le=100, alias="pageSize"),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    q = db.query(Photo).order_by(Photo.upload_time.desc())
    if elder_id:
        q = q.filter(Photo.elderly_id == elder_id)
    if cursor:
        q = q.filter(Photo.id < cursor)
    if start_date:
        q = q.filter(Photo.upload_time >= datetime.fromisoformat(start_date))
    if end_date:
        q = q.filter(Photo.upload_time <= datetime.fromisoformat(end_date))

    photos = q.limit(page_size + 1).all()
    has_more = len(photos) > page_size
    if has_more:
        photos = photos[:page_size]

    items = []
    for p in photos:
        items.append({
            "id": p.id,
            "type": "photo",
            "timestamp": str(p.upload_time),
            "year": p.upload_time.year,
            "month": p.upload_time.month,
            "day": p.upload_time.day,
            "data": {
                "url": f"/uploads/{p.original_path}",
                "thumbnailUrl": f"/uploads/{p.thumbnail_path}" if p.thumbnail_path else None,
                "note": p.note,
                "elderId": p.elderly_id,
                "elderName": p.elderly.name if p.elderly else None
            }
        })
    return {
        "list": items,
        "hasMore": has_more,
        "nextCursor": photos[-1].id if has_more and photos else None
    }

