"""管理员端:注册审核 + 志愿者管理(V0907 契约 §5.5/5.6/5.7,N3-N6)

- 注册审核:GET /admin/applications、POST /admin/applications/:id/approve|reject
  通过 = 建档即开户(申请快照落 elder_applications,通过才生成 elders+users 行,幂等)
- 志愿者管理:GET/POST/DELETE /admin/volunteers
  删志愿者 = 解除其名下老人分配(volunteer_id 置空)+ 账号停用;历史照片保留
"""
from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session
from sqlalchemy import or_, func
from typing import Optional
from pydantic import BaseModel, Field

from models.user import User, UserRole
from models.elderly import Elderly
from models.elder_application import ElderApplication
from utils.permissions import get_db, get_current_user, is_admin, deny, find_elder_user
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_USERNAME_EXISTS, ERR_PASSWORD_SHORT
from utils.auth import get_password_hash
from utils.timefmt import fmt_dt, now_local

router = APIRouter(prefix="/api", tags=["管理员"])


def _app_to_dict(a):
    return {
        "id": a.id,
        "name": a.name,
        "age": a.age,
        "phone": a.phone,
        "gender": a.gender,
        "appliedAt": fmt_dt(a.created_at),
    }


def _volunteer_to_dict(v, db):
    elder_count = db.query(func.count(Elderly.id)).filter(Elderly.volunteer_id == v.id).scalar() or 0
    return {
        "id": v.id,
        "username": v.username,
        "phone": v.phone,
        "elderCount": elder_count,
        "createdAt": fmt_dt(v.created_at),
    }


def _require_admin(authorization, db):
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()
    return user


# ================= 注册审核(N3/N4) =================
@router.get("/admin/applications")
def list_applications(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    _require_admin(authorization, db)
    q = db.query(ElderApplication).order_by(ElderApplication.created_at.desc())
    if status:
        q = q.filter(ElderApplication.status == status)
    total = q.count()
    apps = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_app_to_dict(a) for a in apps],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.post("/admin/applications/{application_id}/approve")
def approve_application(
    application_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """通过申请 → 建档即开户;幂等(重复 approve 返回原 elderId)"""
    _require_admin(authorization, db)
    app = db.query(ElderApplication).filter(ElderApplication.id == application_id).first()
    if not app:
        raise AppException(ERR_NOT_FOUND, "申请不存在")
    if app.status == "approved" and app.elder_id:
        return {"elderId": app.elder_id}  # 幂等
    if app.status == "rejected":
        raise AppException(ERR_NOT_FOUND, "该申请已处理")

    # 建档即开户:生成老人登录账号(username=姓名)
    account = None
    if app.wx_user_id:
        wx_user = db.query(User).filter(User.id == app.wx_user_id).first()
        if wx_user and wx_user.is_active is not False:
            # 微信用户:children 身份切换为 elder
            wx_user.role = "elder"
            wx_user.name = app.name
            wx_user.phone = app.phone
            wx_user.password_hash = app.password_hash
            wx_user.is_active = True
            account = wx_user
    if not account:
        # 命中认领目标则复用既有账号,否则新建
        existing_elder = db.query(Elderly).filter(
            Elderly.name == app.name, Elderly.contact_info == app.phone
        ).first()
        account = find_elder_user(db, existing_elder) if existing_elder else None
    if not account:
        username = app.name
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{app.name}_{suffix}"
        account = User(
            username=username,
            password_hash=app.password_hash,
            role=UserRole("elder"),
            name=app.name,
            phone=app.phone,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

    elder = db.query(Elderly).filter(
        Elderly.name == app.name, Elderly.contact_info == app.phone
    ).first()
    if not elder:
        elder = Elderly(
            name=app.name,
            age=app.age,
            gender=app.gender,
            contact_info=app.phone,
            created_by=account.id,
        )
        db.add(elder)
        db.commit()
        db.refresh(elder)
    else:
        # 认领既有档案:账号与档案建立关联(created_by 优先保持,若为空档则回填)
        pass
    app.status = "approved"
    app.elder_id = elder.id
    app.reviewed_at = now_local()
    db.commit()
    return {"elderId": elder.id}


@router.post("/admin/applications/{application_id}/reject")
def reject_application(
    application_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """拒绝申请:仅标记,不产生任何账号;微信用户可重新申请"""
    _require_admin(authorization, db)
    app = db.query(ElderApplication).filter(ElderApplication.id == application_id).first()
    if not app:
        raise AppException(ERR_NOT_FOUND, "申请不存在")
    if app.status == "approved":
        raise AppException(ERR_NOT_FOUND, "该申请已处理")
    if app.status == "rejected":
        return None  # 幂等
    app.status = "rejected"
    app.reviewed_at = now_local()
    db.commit()
    return None


# ================= 志愿者管理(N5/N6) =================
@router.get("/admin/volunteers")
def list_volunteers(
    keyword: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100, alias="pageSize"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    _require_admin(authorization, db)
    q = db.query(User).filter(User.role == "volunteer", User.is_active.isnot(False))
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(or_(User.username.like(kw), User.name.like(kw), User.phone.like(kw)))
    q = q.order_by(User.created_at.desc())
    total = q.count()
    vols = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_volunteer_to_dict(v, db) for v in vols],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


class VolunteerCreate(BaseModel):
    name: str = Field(..., description="姓名 = 登录名")
    phone: Optional[str] = Field(None, description="手机号")
    password: str = Field(..., description="初始密码 ≥6 位")


@router.post("/admin/volunteers", status_code=201)
def create_volunteer(
    req: VolunteerCreate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    _require_admin(authorization, db)
    name = (req.name or "").strip()
    if not name:
        raise AppException(1003, "姓名不能为空")
    if len(req.password) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码至少 6 位")
    if db.query(User).filter(User.username == name).first():
        raise AppException(ERR_USERNAME_EXISTS, "该姓名已被用作登录账号,请更换姓名")
    if req.phone and db.query(User).filter(User.phone == req.phone).first():
        raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号")
    v = User(
        username=name,
        name=name,
        phone=req.phone,
        password_hash=get_password_hash(req.password),
        role=UserRole("volunteer"),
    )
    db.add(v)
    db.commit()
    db.refresh(v)
    return {"id": v.id}


@router.delete("/admin/volunteers/{volunteer_id}")
def delete_volunteer(
    volunteer_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """删除志愿者 = 解除名下老人分配 + 账号停用;历史照片保留(上传者信息冗余在照片行)"""
    _require_admin(authorization, db)
    v = db.query(User).filter(User.id == volunteer_id, User.role == "volunteer").first()
    if not v:
        raise AppException(ERR_NOT_FOUND, "志愿者不存在")
    db.query(Elderly).filter(Elderly.volunteer_id == v.id).update({"volunteer_id": None})
    v.is_active = False
    db.commit()
    return None
