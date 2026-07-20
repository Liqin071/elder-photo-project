"""志愿者和家属专属接口"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from models.database import SessionLocal
from models.user import User
from models.elderly import Elderly
from models.photo import Photo
from utils.auth import verify_token

router = APIRouter(prefix="/api", tags=["志愿者/家属"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_id(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或token已过期")
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
            "image_count": len(e.photos) if e.photos else 0,
            "last_upload_at": str(last_photo.upload_time) if last_photo else None
        })
    return {"elders": result}


@router.get("/family/parents")
def family_parents(
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    elders = db.query(Elderly).all()
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
                "total_images": total,
                "monthly_images": monthly,
                "unread_messages": 0,
                "latest_image_url": f"/uploads/{latest.original_path}" if latest else None,
                "latest_image_date": str(latest.upload_time) if latest else None
            }
        })
    return {"parents": result}
