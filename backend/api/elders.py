"""老人管理 API — 对齐小程序契约 + 权限矩阵(交接说明 §六)"""
from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import Optional
from pydantic import BaseModel, Field

from models.elderly import Elderly
from models.elderly_child import elderly_child
from utils.permissions import get_db, get_current_user, is_admin, deny, elder_of_user
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_HAS_PHOTOS, ERR_USERNAME_EXISTS
from utils.timefmt import fmt_dt

router = APIRouter(prefix="/api", tags=["老人管理"])


class ElderUpdate(BaseModel):
    name: Optional[str] = Field(None, description="姓名")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    phone: Optional[str] = Field(None, description="联系电话")
    emergencyContact: Optional[str] = Field(None, description="紧急联系人")
    address: Optional[str] = Field(None, description="地址")
    avatar: Optional[str] = Field(None, description="头像URL")
    volunteerId: Optional[int] = Field(None, description="照护志愿者ID")


def _avatar_to_store(avatar):
    """小程序端 avatar 传的是临时路径,不可用(契约 §5.3 建议存 null);只存 http(s) 直链"""
    if avatar and (avatar.startswith("http://") or avatar.startswith("https://")):
        return avatar
    return None


def _elder_to_dict(e):
    volunteer_name = None
    if e.volunteer_id and e.volunteer:
        volunteer_name = e.volunteer.name or e.volunteer.username
    elif e.creator:
        volunteer_name = e.creator.name or e.creator.username
    return {
        "id": e.id, "name": e.name, "age": e.age, "gender": e.gender,
        "phone": e.contact_info, "emergencyContact": e.guardian_contact,
        "address": e.address, "avatar": e.avatar,
        "volunteerId": e.volunteer_id or e.created_by,
        "volunteerName": volunteer_name,
        "childrenIds": [c.id for c in e.children] if e.children else [],
        "childrenNames": [c.name or c.username for c in e.children] if e.children else [],
        "imageCount": len(e.photos) if e.photos else 0,
        "createdAt": fmt_dt(e.created_at), "updatedAt": fmt_dt(e.updated_at)
    }


@router.get("/elders")
def list_elders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    keyword: Optional[str] = None,
    sort_by: str = Query("createdAt", alias="sortBy"),
    sort_order: str = Query("desc", alias="sortOrder"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()  # 矩阵:档案列表仅 admin
    query = db.query(Elderly)
    if keyword:
        kw = f"%{keyword}%"
        query = query.filter(or_(Elderly.name.like(kw), Elderly.contact_info.like(kw)))  # 匹配姓名/手机号
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
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "老人档案不存在", 404)
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != elder_id:
            deny()  # 仅自己
    elif not is_admin(user):
        deny()  # 家属经 /family/parents、志愿者经 /volunteer/elders,不走本接口
    return _elder_to_dict(e)


@router.post("/elders", status_code=201)
def create_elder(
    request: dict,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()  # 矩阵:建档仅 admin
    name = (request.get("name") or "").strip()
    if not name:
        raise AppException(1003, "姓名不能为空", 400)
    phone = (request.get("phone") or "").strip()
    if phone:
        exists = db.query(Elderly).filter(Elderly.contact_info == phone).first()
        if exists:
            raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号", 409)
    e = Elderly(
        name=name,
        age=request.get("age"),
        gender=request.get("gender"),
        contact_info=phone or None,
        guardian_contact=request.get("emergencyContact"),
        address=request.get("address"),
        avatar=_avatar_to_store(request.get("avatar")),
        volunteer_id=request.get("volunteerId"),
        created_by=user.id
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return _elder_to_dict(e)


@router.put("/elders/{elder_id}")
def update_elder(
    elder_id: int,
    req: ElderUpdate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "老人档案不存在", 404)
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != elder_id:
            deny()
        # 白名单(矩阵):老人仅能改 name/age/phone/emergencyContact,其余字段直接忽略
        fields = {"name", "age", "phone", "emergencyContact"}
        data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if k in fields}
    elif is_admin(user):
        data = req.model_dump(exclude_unset=True)
    else:
        deny()  # 矩阵:家属/志愿者无改档案权
    if "name" in data and data["name"] is not None:
        e.name = data["name"]
    if "age" in data and data["age"] is not None:
        e.age = data["age"]
    if "phone" in data and data["phone"] is not None:
        e.contact_info = data["phone"]
    if "emergencyContact" in data and data["emergencyContact"] is not None:
        e.guardian_contact = data["emergencyContact"]
    if "gender" in data and data["gender"] is not None:
        e.gender = data["gender"]
    if "address" in data and data["address"] is not None:
        e.address = data["address"]
    if "avatar" in data:
        e.avatar = _avatar_to_store(data["avatar"])
    if "volunteerId" in data and data["volunteerId"] is not None:
        e.volunteer_id = data["volunteerId"]
    db.commit()
    db.refresh(e)
    return _elder_to_dict(e)


@router.delete("/elders/{elder_id}")
def delete_elder(
    elder_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()  # 矩阵:删档案仅 admin
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "老人档案不存在", 404)
    if e.photos:
        raise AppException(ERR_HAS_PHOTOS, "该老人存在影像数据，不能删除", 409)
    # 先解除家属绑定,避免外键约束报错
    db.execute(elderly_child.delete().where(elderly_child.c.elderly_id == elder_id))
    db.delete(e)
    db.commit()
    return None
