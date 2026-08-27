"""时间线 API — 对齐小程序契约(契约 2.2/2.3/2.4)+ 权限矩阵"""
from fastapi import APIRouter, Depends, Query, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional

from models.photo import Photo
from models.comment import Comment
from utils.permissions import get_db, get_current_user, is_admin, deny, elder_of_user, check_elder_access
from utils.timefmt import fmt_dt, fmt_date

router = APIRouter(prefix="/api", tags=["时间线"])


def _build_full_url(request, path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = str(request.base_url).rstrip("/")
    return base + path


def _resolve_elder_id(db, user, elder_id):
    """
    时间轴可见圈:elder ●(仅自己) / children ●(仅绑定的老人) / volunteer、admin ○(拒绝)。
    返回实际使用的 elder_id。
    """
    if is_admin(user) or user.role == "volunteer":
        deny()
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own:
            deny()
        return own.id  # 忽略传入 elderId,仅自己
    # children
    if elder_id is None:
        deny()
    check_elder_access(db, user, elder_id)
    return elder_id


@router.get("/timeline/years")
def timeline_years(
    request: Request,
    elder_id: Optional[int] = Query(None, alias="elderId"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    eid = _resolve_elder_id(db, user, elder_id)
    rows = db.query(
        func.year(Photo.upload_time).label("year"),
        func.count(Photo.id).label("cnt")
    ).filter(Photo.elderly_id == eid).group_by(
        func.year(Photo.upload_time)
    ).order_by(func.year(Photo.upload_time).desc()).all()
    years = []
    for r in rows:
        # 封面取该年最新一张(与 mock 一致)
        cover = db.query(Photo).filter(
            Photo.elderly_id == eid,
            func.year(Photo.upload_time) == r.year
        ).order_by(Photo.upload_time.desc()).first()
        years.append({
            "year": r.year,
            "count": r.cnt,
            "coverUrl": _build_full_url(request, f"/uploads/{cover.original_path}") if cover else None
        })
    return {"years": years}


@router.get("/timeline/aggregation")
def timeline_aggregation(
    request: Request,
    elder_id: Optional[int] = Query(None, alias="elderId"),
    year: int = Query(...),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    eid = _resolve_elder_id(db, user, elder_id)
    months = []
    for m in range(1, 13):
        q = db.query(Photo).filter(
            Photo.elderly_id == eid,
            func.year(Photo.upload_time) == year,
            func.month(Photo.upload_time) == m
        )
        cnt = q.count()
        if cnt == 0:
            continue
        newest = q.order_by(Photo.upload_time.desc()).first()
        oldest = q.order_by(Photo.upload_time.asc()).first()
        months.append({
            "month": f"{m:02d}",
            "count": cnt,
            "coverUrl": _build_full_url(request, f"/uploads/{newest.original_path}") if newest else None,
            "firstDate": fmt_date(oldest.upload_time) if oldest else None,
            "lastDate": fmt_date(newest.upload_time) if newest else None
        })
    return {"year": year, "months": months}


@router.get("/timeline")
def timeline(
    request: Request,
    elder_id: Optional[int] = Query(None, alias="elderId"),
    year: Optional[int] = None,
    cursor: Optional[int] = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    eid = _resolve_elder_id(db, user, elder_id)

    photos = db.query(Photo).filter(Photo.elderly_id == eid).order_by(Photo.upload_time.desc()).all()
    if year:
        photos = [p for p in photos if p.upload_time and p.upload_time.year == year]

    # 影像事件:按日期分组(契约 2.4:同日期前 4 张进 covers,notes 去重取前 2)
    groups = {}
    for p in photos:
        key = fmt_date(p.upload_time)
        groups.setdefault(key, []).append(p)

    events = []
    for date in sorted(groups.keys(), reverse=True):
        group = groups[date]
        first = group[0]  # 该日最新一张
        notes = []
        for p in group:
            if p.note and p.note not in notes:
                notes.append(p.note)
        uploader_name = None
        if first.volunteer:
            uploader_name = first.volunteer.name or first.volunteer.username
        events.append({
            "id": f"img-{date}",
            "type": "image",
            "timestamp": fmt_dt(first.upload_time),
            "year": date[:4],
            "month": date[5:7],
            "day": date[8:10],
            "data": {
                "count": len(group),
                "covers": [
                    {"id": p.id, "url": _build_full_url(request, f"/uploads/{p.thumbnail_path or p.original_path}")}
                    for p in group[:4]
                ],
                "notes": notes[:2],
                "uploaderName": uploader_name,
                "uploaderRole": first.volunteer.role if first.volunteer else None,
            }
        })

    # 留言事件:该老人名下照片的全部文字留言(语音不进时间轴,契约 2.4)
    if photos:
        photo_ids = [p.id for p in photos]
        comments = db.query(Comment).filter(
            Comment.target_type.in_(("image", "photo")),
            Comment.target_id.in_(photo_ids),
            Comment.content_type == "text",
        ).order_by(Comment.created_at.desc()).all()
        for c in comments:
            author = c.author
            author_name = author.name if author else (author.username if author else "匿名")
            ts = fmt_dt(c.created_at)
            events.append({
                "id": f"cmt-{c.id}",
                "type": "comment",
                "timestamp": ts,
                "year": ts[:4],
                "month": ts[5:7],
                "day": ts[8:10],
                "data": {
                    "authorName": author_name,
                    "authorRole": author.role if author else None,
                    "content": c.content or "",
                    "targetImageId": c.target_id
                }
            })

    # 混合事件按 timestamp 降序(契约:字符串比较排序)
    events.sort(key=lambda x: x["timestamp"], reverse=True)

    # 游标语义自由(契约 2.4):此处用 offset;前端原样透传
    start = int(cursor or 0)
    page_list = events[start:start + page_size]
    has_more = start + page_size < len(events)
    return {
        "list": page_list,
        "hasMore": has_more,
        "nextCursor": min(start + page_size, len(events))
    }
