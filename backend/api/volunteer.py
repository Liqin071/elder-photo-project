"""志愿者和家属专属接口"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

from models.database import SessionLocal
from models.user import User
from models.elderly import Elderly
from models.photo import Photo
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_AUTH_REQUIRED, ERR_NOT_FOUND

router = APIRouter(prefix="/api", tags=["志愿者/家属"])



def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_id(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    return user_id


@router.get("/volunteer/elders")
def volunteer_elders(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    elders = db.query(Elderly).filter(Elderly.created_by == user_id).all()
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
            "lastUploadAt": str(last_photo.upload_time) if last_photo else None
        })
    return {"elders": result}


@router.get("/family/parents")
def family_parents(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    elders = user.parent_elders if user else []
    result = []
    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)
    for e in elders:
        total = db.query(Photo).filter(Photo.elderly_id == e.id).count()
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
            "relationship": None,
            "avatar": e.avatar,
            "stats": {
                "totalImages": total,
                "monthlyImages": monthly,
                "unreadMessages": 0,
                "latestImageUrl": f"/uploads/{latest.original_path}" if latest else None,
                "latestImageDate": str(latest.upload_time) if latest else None
            }
        })
    return {"parents": result}


class BindRequest(BaseModel):
    elderId: int = Field(..., description="老人ID")


@router.post("/family/bind")
def family_bind(
    req: BindRequest,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    elder = db.query(Elderly).filter(Elderly.id == req.elderId).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "老人不存在", 404)
    user = db.query(User).filter(User.id == user_id).first()
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
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    elder = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "老人不存在", 404)
    user = db.query(User).filter(User.id == user_id).first()
    if elder in user.parent_elders:
        user.parent_elders.remove(elder)
        db.commit()
    return {"message": "已解绑"}
