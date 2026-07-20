"""老人管理 API"""
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from models.database import SessionLocal
from models.user import User
from models.elderly import Elderly
from utils.auth import verify_token

router = APIRouter(prefix="/api", tags=["老人管理"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_id(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未登录或token已过期")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或token已过期")
    return user_id


def _elder_to_dict(e):
    return {
        "id": e.id, "name": e.name, "age": e.age, "gender": e.gender,
        "phone": e.contact_info, "emergency_contact": e.guardian_contact,
        "address": e.address, "avatar": e.avatar,
        "volunteer_id": e.created_by,
        "volunteer_name": e.creator.name if e.creator else None,
        "image_count": len(e.photos) if e.photos else 0,
        "created_at": str(e.created_at), "updated_at": str(e.updated_at)
    }


@router.get("/elders")
def list_elders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    query = db.query(Elderly)
    if keyword:
        query = query.filter(Elderly.name.contains(keyword))
    total = query.count()
    col = getattr(Elderly, sort_by, Elderly.created_at)
    query = query.order_by(col.desc() if sort_order == "desc" else col.asc())
    elders = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_elder_to_dict(e) for e in elders],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.get("/elders/{elder_id}")
def get_elder(
    elder_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="资源不存在")
    return _elder_to_dict(e)


@router.post("/elders", status_code=201)
def create_elder(
    request: dict,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = Elderly(
        name=request["name"],
        age=request.get("age"),
        gender=request.get("gender"),
        contact_info=request.get("phone"),
        guardian_contact=request.get("emergencyContact"),
        address=request.get("address"),
        avatar=request.get("avatar"),
        created_by=user_id
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _elder_to_dict(e)


@router.put("/elders/{elder_id}")
def update_elder(
    elder_id: int,
    request: dict,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="资源不存在")
    field_map = {
        "name": "name", "age": "age", "gender": "gender",
        "phone": "contact_info", "emergencyContact": "guardian_contact",
        "address": "address", "avatar": "avatar"
    }
    for api_field, db_field in field_map.items():
        if api_field in request:
            setattr(e, db_field, request[api_field])
    e.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(e)
    return _elder_to_dict(e)


@router.delete("/elders/{elder_id}")
def delete_elder(
    elder_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="资源不存在")
    if e.photos:
        raise HTTPException(status_code=409, detail="有影像数据不能删")
    db.delete(e)
    db.commit()
    return None
