"""老人管理 API"""
from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field

from models.database import SessionLocal
from models.user import User
from models.elderly import Elderly
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_HAS_PHOTOS, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["老人管理"])


class ElderUpdate(BaseModel):
    name: Optional[str] = Field(None, description="姓名")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    phone: Optional[str] = Field(None, description="联系电话")
    emergencyContact: Optional[str] = Field(None, description="紧急联系人")
    address: Optional[str] = Field(None, description="地址")
    avatar: Optional[str] = Field(None, description="头像URL")


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


def _elder_to_dict(e):
    return {
        "id": e.id, "name": e.name, "age": e.age, "gender": e.gender,
        "phone": e.contact_info, "emergencyContact": e.guardian_contact,
        "address": e.address, "avatar": e.avatar,
        "volunteerId": e.created_by,
        "volunteerName": e.creator.name if e.creator else None,
        "childrenIds": [c.id for c in e.children] if e.children else [],
        "childrenNames": [c.name or c.username for c in e.children] if e.children else [],
        "imageCount": len(e.photos) if e.photos else 0,
        "createdAt": str(e.created_at), "updatedAt": str(e.updated_at)
    }


@router.get("/elders")
def list_elders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    keyword: Optional[str] = None,
    sort_by: str = Query("createdAt", alias="sortBy"),
    sort_order: str = Query("desc", alias="sortOrder"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    query = db.query(Elderly)
    if keyword:
        query = query.filter(Elderly.name.contains(keyword))
    total = query.count()
    sort_col = "created_at" if sort_by == "createdAt" else sort_by
    col = getattr(Elderly, sort_col, Elderly.created_at)
    query = query.order_by(col.desc() if sort_order == "desc" else col.asc())
    elders = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_elder_to_dict(e) for e in elders],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.get("/elders/{elder_id}")
def get_elder(
    elder_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
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
    req: ElderUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    if req.name is not None:
        e.name = req.name
    if req.age is not None:
        e.age = req.age
    if req.gender is not None:
        e.gender = req.gender
    if req.phone is not None:
        e.contact_info = req.phone
    if req.emergencyContact is not None:
        e.guardian_contact = req.emergencyContact
    if req.address is not None:
        e.address = req.address
    if req.avatar is not None:
        e.avatar = req.avatar
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
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    if e.photos:
        raise AppException(ERR_HAS_PHOTOS, "有影像数据不能删", 409)
    db.delete(e)
    db.commit()
    return None
