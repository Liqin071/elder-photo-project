"""志愿者和家属专属 API — 对齐小程序契约 + 权限矩阵"""
from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from pydantic import BaseModel, Field

from models.elderly import Elderly
from models.photo import Photo
from utils.permissions import get_db, get_current_user, deny, get_elder_relationship, unread_comment_count
from utils.exceptions import AppException, ERR_NOT_FOUND
from utils.timefmt import fmt_date, now_local

router = APIRouter(prefix="/api", tags=["志愿者/家属"])


@router.get("/volunteer/elders")
def volunteer_elders(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if user.role != "volunteer":
        deny()  # 矩阵:仅志愿者
    # 分配关系:优先 volunteer_id,旧数据 created_by 兜底(交接说明 §四/§六)
    elders = db.query(Elderly).filter(
        or_(Elderly.volunteer_id == user.id, Elderly.created_by == user.id)
    ).all()
    result = []
    for e in elders:
        last_photo = db.query(Photo).filter(
            Photo.elderly_id == e.id
        ).order_by(Photo.upload_time.desc()).first()
        result.append({
            "id": e.id,
            "name": e.name,
            "age": e.age,
            "avatar": e.avatar,
            "imageCount": len(e.photos) if e.photos else 0,
            "lastUploadAt": fmt_date(last_photo.upload_time) if last_photo else None
        })
    return {"elders": result}


@router.get("/family/parents")
def family_parents(
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if user.role != "children":
        deny()  # 矩阵:仅家属端消费
    elders = user.parent_elders if user else []
    result = []
    for e in elders:
        total = db.query(Photo).filter(Photo.elderly_id == e.id).count()
        now = now_local()
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        monthly = db.query(Photo).filter(
            Photo.elderly_id == e.id,
            Photo.upload_time >= month_start
        ).count()
        latest = db.query(Photo).filter(
            Photo.elderly_id == e.id
        ).order_by(Photo.upload_time.desc()).first()
        result.append({
            "id": e.id,
            "name": e.name,
            "relationship": get_elder_relationship(db, user.id, e.id),
            "avatar": e.avatar,
            "stats": {
                "totalImages": total,
                "monthlyImages": monthly,
                # 契约 2.1:该老人名下当前家属未读的留言通知数(metadata.elderId 匹配)
                "unreadMessages": unread_comment_count(db, user.id, e.id),
                "latestImageUrl": _photo_url(request, latest) if latest else None,
                "latestImageDate": fmt_date(latest.upload_time) if latest else None
            }
        })
    return {"parents": result}


def _photo_url(request, photo):
    if not photo:
        return None
    base = str(request.base_url).rstrip("/")
    return base + f"/uploads/{photo.thumbnail_path or photo.original_path}"


class BindRequest(BaseModel):
    elderId: int = Field(..., description="老人ID")


@router.post("/family/bind")
def family_bind(
    req: BindRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    elder = db.query(Elderly).filter(Elderly.id == req.elderId).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "老人不存在", 404)
    if elder in user.parent_elders:
        return {"message": "已绑定", "elderId": elder.id, "elderName": elder.name}
    user.parent_elders.append(elder)
    db.commit()
    return {
        "message": "绑定成功",
        "elderId": elder.id,
        "elderName": elder.name,
        "volunteerName": elder.creator.name if elder.creator else None
    }


@router.delete("/family/bind/{elder_id}")
def family_unbind(
    elder_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    elder = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "老人不存在", 404)
    if elder in user.parent_elders:
        user.parent_elders.remove(elder)
        db.commit()
    return {"message": "已解绑"}
