"""老人管理 API — 对齐 V0907 契约(§3/§4/§5/§6)+ 权限矩阵

2026-08-28 登录注册重构要点:
- POST /elders 建档即开户:admin / volunteer 可建;password 必填(老人登录初始密码)
- volunteer 建/改老人(仅自己照护的),DELETE 一律 2003;admin 可删(有影像 2002,级联停用老人账号)
- admin PUT 支持 volunteerId(分配/解除)+ password(重置登录密码)
- GET /elders/:id/families 老人本人/admin 查绑定家属(N7)
- POST /elders/avatar admin/volunteer 传头像 → {url}(§6.3)
"""
from fastapi import APIRouter, Depends, Query, Header, Request, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import or_, select
from typing import Optional
from pydantic import BaseModel, Field
import os
import uuid

from models.user import User, UserRole
from models.elderly import Elderly
from models.elder_application import ElderApplication
from models.elderly_child import elderly_child
from utils.permissions import (
    get_db, get_current_user, is_admin, deny, elder_of_user, find_elder_user, check_elder_access,
)
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_HAS_PHOTOS, ERR_USERNAME_EXISTS, ERR_PASSWORD_SHORT, ERR_NO_PERMISSION
from utils.auth import get_password_hash
from utils.timefmt import fmt_dt

router = APIRouter(prefix="/api", tags=["老人管理"])

AVATAR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "avatars")
os.makedirs(AVATAR_DIR, exist_ok=True)
ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "application/octet-stream"}
ALLOWED_AVATAR_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


class ElderUpdate(BaseModel):
    name: Optional[str] = Field(None, description="姓名")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    phone: Optional[str] = Field(None, description="联系电话")
    emergencyContact: Optional[str] = Field(None, description="紧急联系人")
    address: Optional[str] = Field(None, description="地址")
    avatar: Optional[str] = Field(None, description="头像URL")
    volunteerId: Optional[int] = Field(None, description="照护志愿者ID(null 解除分配,仅 admin)")
    password: Optional[str] = Field(None, description="重置老人登录密码 ≥6 位(仅 admin)")


def _avatar_to_store(avatar):
    if avatar and (avatar.startswith("http://") or avatar.startswith("https://")):
        return avatar
    return None


def _elder_to_dict(e):
    volunteer_name = None
    if e.volunteer_id and e.volunteer:
        volunteer_name = e.volunteer.name or e.volunteer.username
    elif e.creator and e.creator.role == "volunteer":
        volunteer_name = e.creator.name or e.creator.username
    return {
        "id": e.id, "name": e.name, "age": e.age, "gender": e.gender,
        "phone": e.contact_info, "emergencyContact": e.guardian_contact,
        "address": e.address, "avatar": e.avatar,
        "volunteerId": e.volunteer_id,
        "volunteerName": volunteer_name,
        "childrenIds": [c.id for c in e.children] if e.children else [],
        "childrenNames": [c.name or c.username for c in e.children] if e.children else [],
        "imageCount": len(e.photos) if e.photos else 0,
        "createdAt": fmt_dt(e.created_at), "updatedAt": fmt_dt(e.updated_at)
    }


def _name_taken(db, name, exclude_user_id=None):
    return db.query(User).filter(User.username == name, User.id != (exclude_user_id or -1)).first() is not None


def _create_elder_user(db, name, phone, password, is_active=True):
    """建档即开户:创建老人登录账号(username=姓名)"""
    user = User(
        username=name,
        password_hash=get_password_hash(password),
        role=UserRole("elder"),
        name=name,
        phone=phone,
        is_active=is_active,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


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
        query = query.filter(or_(Elderly.name.like(kw), Elderly.contact_info.like(kw)))
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
        raise AppException(ERR_NOT_FOUND, "老人档案不存在")
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
    """建档即开户(契约 5.2/4.2):admin / volunteer 可建;volunteer 自动分配给自己"""
    user = get_current_user(authorization, db)
    if not is_admin(user) and user.role != "volunteer":
        deny()  # 老人/家属无建档权
    name = (request.get("name") or "").strip()
    phone = (request.get("phone") or "").strip()
    password = request.get("password") or ""
    if not name:
        raise AppException(1003, "姓名不能为空")
    if len(password) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码至少 6 位")
    if _name_taken(db, name):
        raise AppException(ERR_USERNAME_EXISTS, "该姓名已被用作登录账号,请更换姓名")
    if db.query(Elderly).filter(Elderly.contact_info == phone).first():
        raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号")

    # 建档即开户:老人登录账号(username=姓名)
    account = _create_elder_user(db, name, phone, password)
    e = Elderly(
        name=name,
        age=request.get("age"),
        gender=request.get("gender"),
        contact_info=phone or None,
        guardian_contact=request.get("emergencyContact"),
        address=request.get("address"),
        avatar=_avatar_to_store(request.get("avatar")),
        volunteer_id=user.id if user.role == "volunteer" else request.get("volunteerId"),
        created_by=account.id,
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
        raise AppException(ERR_NOT_FOUND, "老人档案不存在")
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != elder_id:
            deny()
        # 白名单(矩阵):老人仅能改 name/age/phone/emergencyContact
        data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if k in ("name", "age", "phone", "emergencyContact")}
    elif user.role == "volunteer":
        # 仅自己照护的老人;字段与管理员一致但不含 volunteerId/password(决策点 4)
        check_elder_access(db, user, elder_id)
        data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if k in ("name", "age", "gender", "phone", "emergencyContact", "address", "avatar")}
    elif is_admin(user):
        data = req.model_dump(exclude_unset=True)
    else:
        deny()

    name_change = "name" in data and data["name"] and data["name"] != e.name
    old_name = e.name
    account = find_elder_user(db, e) if (name_change or "password" in data) else None
    if name_change and _name_taken(db, data["name"], exclude_user_id=account.id if account else None):
        raise AppException(ERR_USERNAME_EXISTS, "该姓名已被用作登录账号,请更换姓名")

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
    if "volunteerId" in data and is_admin(user):
        e.volunteer_id = data["volunteerId"]
    if "password" in data and data["password"] and is_admin(user):
        if len(data["password"]) < 6:
            raise AppException(ERR_PASSWORD_SHORT, "密码至少 6 位")
        if account:
            account.password_hash = get_password_hash(data["password"])
    if name_change and account:
        # 同步账号展示姓名;若账号登录名恰为旧档案名则一并更新(避免改档案后登录名脱节)
        account.name = e.name
        if account.username == old_name:
            account.username = e.name
    db.commit()
    db.refresh(e)
    return _elder_to_dict(e)


@router.delete("/elders/{elder_id}")
def delete_elder(
    elder_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """删档案:仅 admin(volunteer 一律 2003);有影像 2002;级联停用老人登录账号与绑定"""
    user = get_current_user(authorization, db)
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "老人档案不存在")
    if user.role == "volunteer":
        raise AppException(ERR_NO_PERMISSION, "无权限操作")
    if not is_admin(user):
        deny()
    if e.photos:
        raise AppException(ERR_HAS_PHOTOS, "该老人存在影像数据，不能删除")
    # 级联:解除家属绑定
    db.execute(elderly_child.delete().where(elderly_child.c.elderly_id == elder_id))
    # 级联:申请记录(approve 回填了 elder_id)解除引用,避免外键拦删除
    db.execute(ElderApplication.__table__.update().where(
        ElderApplication.elder_id == elder_id).values(elder_id=None))
    # 级联:停用老人登录账号(软删,保护外键与历史)
    account = find_elder_user(db, e)
    if account:
        account.is_active = False
    db.delete(e)
    db.commit()
    return None


# ---------- N7:老人视角的绑定家属列表 ----------
@router.get("/elders/{elder_id}/families")
def elder_families(
    elder_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    e = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not e:
        raise AppException(ERR_NOT_FOUND, "老人档案不存在")
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != elder_id:
            deny()
    elif not is_admin(user):
        deny()  # 仅老人本人/admin 可查
    rows = db.execute(
        select(
            elderly_child.c.child_id.label("child_id"),
            elderly_child.c.relationship.label("relationship"),
            elderly_child.c.created_at.label("bind_created_at"),
            User.name.label("user_name"),
            User.username.label("user_username"),
            User.avatar.label("user_avatar"),
            User.created_at.label("user_created_at"),
        ).join(User, User.id == elderly_child.c.child_id).where(
            elderly_child.c.elderly_id == elder_id
        )
    ).all()
    families = []
    for r in rows:
        # 老数据 created_at 可能为空:回退到家属账号创建时间做展示
        bound_at = fmt_dt(r.bind_created_at) or fmt_dt(r.user_created_at)
        families.append({
            "userId": r.child_id,
            "username": r.user_name or r.user_username,
            "relationship": r.relationship or "家人",
            "avatar": r.user_avatar,
            "boundAt": bound_at,
        })
    return {"families": families}


# ---------- §6.3:头像上传(admin/volunteer)→ {url} ----------
@router.post("/elders/avatar", status_code=200)
async def upload_elder_avatar(
    request: Request,
    file: UploadFile = File(...),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not is_admin(user) and user.role != "volunteer":
        deny()
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if (file.content_type or "").lower() not in ALLOWED_AVATAR_TYPES and ext not in ALLOWED_AVATAR_EXTS:
        raise AppException(3001, "文件类型不支持")
    contents = await file.read()
    if len(contents) > 5 * 1024 * 1024:
        raise AppException(3002, "头像不能超过 5MB")
    filename = f"{uuid.uuid4().hex}.{ext or 'jpg'}"
    with open(os.path.join(AVATAR_DIR, filename), "wb") as f:
        f.write(contents)
    base = str(request.base_url).rstrip("/")
    return {"url": base + f"/uploads/avatars/{filename}"}
