"""用户认证 API — 对齐 V0907 契约(37 接口 §1/§7)

2026-08-28 登录注册重构要点:
- 登录失败统一返回业务错误(HTTP 200 + code≠0,"用户名或密码错误"),不再 HTTP 401(401 仅用于未登录/token 失效)
- 老人自助注册 = 申请→管理员审核(pending);姓名+手机号命中已有档案 → 认领直激活(activated,发新 token+user)
- 家属自助注册 = 免审核即时生效(register-children),注册即登录即绑定
- bind-elder 仅 children 角色可调,支持 relationship,重复绑定友好提示,绑定成功通知老人
- users/me:资料(phone)+ 改密;志愿者/管理员由管理员端开号(见 api/admin_ops.py)
"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from models.user import User, UserRole
from models.elderly import Elderly
from models.elder_application import ElderApplication
from utils.auth import get_password_hash, verify_password, create_access_token, verify_token
from utils.exceptions import AppException, ERR_AUTH_FAILED, ERR_AUTH_REQUIRED, ERR_USERNAME_EXISTS, ERR_PASSWORD_SHORT, ERR_NOT_FOUND, ERR_ACCOUNT_DISABLED
from utils.permissions import get_db, get_current_user, deny, elder_of_user, find_elder_user, add_binding
from utils.notify import notify_bind_elder
from utils.timefmt import now_local
import httpx
import os

router = APIRouter(prefix="/api", tags=["auth"])


# ---------- 请求模型 ----------
class UserLogin(BaseModel):
    username: str
    password: str

class UserRegister(BaseModel):
    username: str
    password: str
    role: str = "volunteer"
    name: Optional[str] = None
    phone: Optional[str] = None
    bindCode: Optional[str] = None

class WxLogin(BaseModel):
    code: str
    nickName: Optional[str] = None
    avatarUrl: Optional[str] = None

class BindElderRequest(BaseModel):
    name: str = Field(..., description="老人姓名")
    phone: str = Field(..., description="老人联系电话")
    relationship: Optional[str] = Field(None, description="与老人的关系(选填,母亲/父亲/儿子/...)")

class RegisterElderRequest(BaseModel):
    name: str = Field(..., description="姓名 = 通过后的登录名")
    phone: str = Field(..., description="联系电话")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别")
    password: str = Field(..., description="初始密码 ≥6 位")

class RegisterChildrenRequest(BaseModel):
    username: str = Field(..., description="登录用户名")
    phone: str = Field(..., description="家属手机号")
    password: str = Field(..., description="密码 ≥6 位")
    elderName: str = Field(..., description="要绑定的老人姓名")
    elderPhone: str = Field(..., description="要绑定的老人电话")
    relationship: Optional[str] = Field(None, description="与老人的关系(选填)")

class UpdateMeRequest(BaseModel):
    phone: Optional[str] = Field(None, description="手机号(唯一可改字段)")

class ChangePasswordRequest(BaseModel):
    oldPassword: str = Field(..., description="旧密码")
    newPassword: str = Field(..., description="新密码 ≥6 位")


# ---------- 内部辅助 ----------
def _build_user_info(db_user, db):
    info = {
        "id": db_user.id,
        "username": db_user.username,
        "role": db_user.role,
        "name": db_user.name,
        "avatar": db_user.avatar,
        "phone": db_user.phone,
    }
    if db_user.role == "elder":
        elder = elder_of_user(db, db_user)
        if elder:
            info["elderId"] = elder.id
            info["bound"] = True
    elif db_user.role == "children":
        info["bound"] = len(db_user.parent_elders) > 0
    else:
        info["bound"] = True
    return info


def _resolve_bearer_user(authorization, db):
    """可选鉴权:带合法 token 返回 User,否则 None(register-elder 的微信认领分支用)"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    uid = verify_token(authorization.split(" ")[1])
    if not uid:
        return None
    return db.query(User).filter(User.id == uid).first()


def _user_me_dict(u):
    return {"id": u.id, "username": u.username, "phone": u.phone, "role": u.role}


def _wx_apply_status(db, user_id):
    """该微信用户最新一条老人注册申请的状态;无申请 → None"""
    app = db.query(ElderApplication).filter(
        ElderApplication.wx_user_id == user_id
    ).order_by(ElderApplication.id.desc()).first()
    if app and app.status in ("pending", "rejected"):
        return app.status
    return None


def _unique_phone_taken(db, phone, exclude_user_id=None):
    """phone 全局占用检查:users.phone / elderly.contact_info / 未决申请"""
    if db.query(User).filter(User.phone == phone, User.id != (exclude_user_id or -1)).first():
        return True
    if db.query(Elderly).filter(Elderly.contact_info == phone).first():
        return True
    if db.query(ElderApplication).filter(
        ElderApplication.phone == phone,
        ElderApplication.status.in_(("pending", "approved")),
    ).first():
        return True
    return False


# ---------- 登录 / 注册(web 兼容) ----------
@router.post("/auth/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user:
        # 老人端便利:前端注册老人时只收姓名+手机号;后端默认密码 = 手机号。
        # 用户名填 11 位手机号时,按 elder 角色的 phone 匹配账号。
        if user.username.isdigit() and len(user.username) == 11:
            db_user = db.query(User).filter(
                User.phone == user.username, User.role == "elder"
            ).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise AppException(ERR_AUTH_FAILED, "用户名或密码错误")
    if db_user.is_active is False:
        raise AppException(ERR_ACCOUNT_DISABLED, "账户已被禁用")
    token = create_access_token(db_user.id, db_user.role)
    db_user.last_login = now_local()
    db.commit()
    return {
        "token": token,
        "user": _build_user_info(db_user, db)
    }


@router.post("/auth/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    """web 端遗留注册入口:仅志愿者可自助注册(红线:管理员手工建号)"""
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise AppException(ERR_USERNAME_EXISTS, "用户名已存在")
    if len(user.password) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码长度不足")
    role = "volunteer" if user.role not in ("volunteer",) else user.role
    new_user = User(
        username=user.username,
        password_hash=get_password_hash(user.password),
        role=UserRole(role),
        name=user.name,
        phone=user.phone
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "id": new_user.id,
        "username": new_user.username,
        "role": new_user.role
    }


# ---------- 微信登录 ----------
@router.post("/auth/wx-login")
async def wx_login(data: WxLogin, db: Session = Depends(get_db)):
    WX_APPID = os.getenv("WX_APPID", "")
    WX_SECRET = os.getenv("WX_SECRET", "")
    if not WX_APPID or not WX_SECRET:
        raise AppException(5000, "微信登录未配置")
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": WX_APPID,
                "secret": WX_SECRET,
                "js_code": data.code,
                "grant_type": "authorization_code"
            }
        )
    wx_data = resp.json()
    if "errcode" in wx_data and wx_data["errcode"] != 0:
        raise AppException(5000, f"微信登录失败: {wx_data.get('errmsg', '')}")
    openid = wx_data["openid"]
    user = db.query(User).filter(User.openid == openid).first()
    if not user:
        base = "微信用户"
        username = base
        i = 1
        while db.query(User).filter(User.username == username).first():
            i += 1
            username = f"{base}_{i}"
        user = User(
            username=username,
            password_hash="",
            role=UserRole("children"),
            openid=openid,
            name=data.nickName or "微信用户",
            avatar=data.avatarUrl
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    if user.is_active is False:
        raise AppException(ERR_ACCOUNT_DISABLED, "账户已被禁用")
    token = create_access_token(user.id, user.role)
    payload = _build_user_info(user, db)
    payload["openid"] = user.openid
    if user.role == "children":
        payload["bound"] = len(user.parent_elders) > 0
        payload["applyStatus"] = None if payload["bound"] else _wx_apply_status(db, user.id)
    return {"token": token, "user": payload}


# ---------- 家属绑定 ----------
@router.post("/auth/bind-elder")
def bind_elder(
    req: BindElderRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """绑定老人:仅 children 角色;姓名+电话全等匹配;重复绑定友好提示;成功后通知老人"""
    user = get_current_user(authorization, db)
    if user.role != "children":
        deny()  # 契约 1.3:仅家属可绑(volunteer/elder/admin → 2003)
    elder = db.query(Elderly).filter(
        Elderly.name == req.name,
        Elderly.contact_info == req.phone
    ).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "未找到匹配的老人档案,请核对姓名和电话")
    added = add_binding(db, user.id, elder.id, req.relationship)
    if not added:
        raise AppException(ERR_NOT_FOUND, "已绑定该老人")  # 幂等友好提示
    notify_bind_elder(db, elder, user.name or user.username)
    return {"elderId": elder.id, "elderName": elder.name}


# ---------- 老人自助注册(申请 → 审核 / 认领直激活) ----------
@router.post("/auth/register-elder")
def register_elder(
    req: RegisterElderRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    name = (req.name or "").strip()
    phone = (req.phone or "").strip()
    if not name or not phone:
        raise AppException(1003, "姓名和手机号不能为空")
    if len((req.password or "")) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码至少 6 位")
    wx_user = _resolve_bearer_user(authorization, db)

    # 分支 B:认领直激活 —— 姓名+手机号已命中管理员/志愿者建的档案
    elder = db.query(Elderly).filter(
        Elderly.name == name,
        Elderly.contact_info == phone
    ).first()
    if elder:
        return _claim_activate(db, wx_user, elder, name, phone, req.password)

    # 分支 A:全新申请
    if _unique_phone_taken(db, phone):
        raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号")
    if db.query(User).filter(User.username == name).first():
        raise AppException(ERR_USERNAME_EXISTS, "该姓名已被用作登录账号,请更换姓名")
    app = ElderApplication(
        name=name,
        age=req.age,
        gender=req.gender,
        phone=phone,
        password_hash=get_password_hash(req.password),
        status="pending",
        wx_user_id=wx_user.id if wx_user else None,
    )
    db.add(app)
    db.commit()
    db.refresh(app)
    return {"status": "pending", "applicationId": app.id}


def _claim_activate(db, wx_user, elder, name, phone, password):
    """
    认领直激活:为已有档案的老人开通/重置登录账号。
    - 微信路径(wx_user 有 openid 且是 children):role 切 elder、落档案关联,发新 token+user
    - 普通路径:建档即开户(创建 role=elder 账号),token/user 供直接登录
    """
    account = find_elder_user(db, elder)
    if wx_user and wx_user.openid and not account:
        # 微信用户认领:当前 children 身份切换为 elder
        wx_user.role = "elder"
        wx_user.name = name
        wx_user.phone = phone
        wx_user.password_hash = get_password_hash(password)
        account = wx_user
    if not account:
        username = name
        suffix = 1
        while db.query(User).filter(User.username == username).first():
            suffix += 1
            username = f"{name}_{suffix}"
        account = User(
            username=username,
            password_hash=get_password_hash(password),
            role=UserRole("elder"),
            name=name,
            phone=phone,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
    else:
        # 已有账号:重置为其本次注册设定的密码(认领后以新密码登录)
        account.password_hash = get_password_hash(password)
        if account.role != "elder":
            account.role = "elder"
            account.name = name
            account.phone = phone
        db.commit()
        db.refresh(account)
    token = create_access_token(account.id, account.role)
    return {
        "status": "activated",
        "elderId": elder.id,
        "token": token,
        "user": _build_user_info(account, db),
    }


# ---------- 家属自助注册(免审核,注册即登录即绑定) ----------
@router.post("/auth/register-children")
def register_children(req: RegisterChildrenRequest, db: Session = Depends(get_db)):
    username = (req.username or "").strip()
    phone = (req.phone or "").strip()
    if not username or not phone:
        raise AppException(1003, "用户名和手机号不能为空")
    if len((req.password or "")) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码至少 6 位")
    if db.query(User).filter(User.username == username).first():
        raise AppException(ERR_USERNAME_EXISTS, "该用户名已被使用,请更换")
    if db.query(User).filter(User.phone == phone).first():
        raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号")
    elder = db.query(Elderly).filter(
        Elderly.name == req.elderName,
        Elderly.contact_info == req.elderPhone
    ).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "未找到该老人(或待管理员审核),请核对姓名和电话")
    new_user = User(
        username=username,
        password_hash=get_password_hash(req.password),
        role=UserRole("children"),
        name=username,
        phone=phone,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    add_binding(db, new_user.id, elder.id, req.relationship)
    notify_bind_elder(db, elder, new_user.name or new_user.username)
    token = create_access_token(new_user.id, new_user.role)
    return {
        "token": token,
        "user": {
            "id": new_user.id,
            "username": new_user.username,
            "role": "children",
            "bound": True,
        }
    }


# ---------- 用户自助(§7) ----------
@router.get("/users/me")
def get_me(
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    return _user_me_dict(user)


@router.put("/users/me")
def update_me(
    req: UpdateMeRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    # 契约 §7.2:仅 phone 可改;username/role 等一律忽略
    if req.phone is not None:
        dup = db.query(User).filter(User.phone == req.phone, User.id != user.id).first()
        if dup:
            raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号")
        user.phone = req.phone
        db.commit()
    return _user_me_dict(user)


@router.put("/users/me/password")
def change_password(
    req: ChangePasswordRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not verify_password(req.oldPassword, user.password_hash):
        raise AppException(1003, "旧密码不正确")
    if len((req.newPassword or "")) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "新密码至少 6 位")
    user.password_hash = get_password_hash(req.newPassword)
    db.commit()
    return None


@router.delete("/users/me")
def delete_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    """注销账号:软删(禁用),保护照片/留言等外键与历史展示"""
    user = get_current_user(authorization, db)
    user.is_active = False
    db.commit()
    return {"message": "账号已注销"}
