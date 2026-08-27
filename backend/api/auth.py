"""用户认证 API — 对齐小程序前端契约"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
from models.user import User, UserRole
from models.elderly import Elderly
from utils.auth import get_password_hash, verify_password, create_access_token, verify_token
from utils.exceptions import AppException, ERR_AUTH_FAILED, ERR_AUTH_REQUIRED, ERR_USERNAME_EXISTS, ERR_PASSWORD_SHORT, ERR_NOT_FOUND
from utils.permissions import get_db, elder_of_user
from utils.timefmt import now_local
import httpx
import os

router = APIRouter(prefix="/api", tags=["auth"])

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

class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, description="姓名")
    avatar: Optional[str] = Field(None, description="头像URL")
    phone: Optional[str] = Field(None, description="手机号")

class BindElderRequest(BaseModel):
    name: str = Field(..., description="老人姓名")
    phone: str = Field(..., description="老人联系电话")

class RegisterElderRequest(BaseModel):
    name: str = Field(..., description="老人姓名")
    phone: str = Field(..., description="老人联系电话")
    emergencyContact: Optional[str] = Field(None, description="紧急联系人")

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
        # 定位自己的老人档案(created_by → name → phone 兜底链,兼容管理员代建档场景)
        elder = elder_of_user(db, db_user)
        if elder:
            info["elderId"] = elder.id
            info["bound"] = True
    elif db_user.role == "children":
        info["bound"] = len(db_user.parent_elders) > 0
    else:
        info["bound"] = True
    return info

@router.post("/auth/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise AppException(ERR_AUTH_FAILED, "用户名或密码错误", 401)
    token = create_access_token(db_user.id, db_user.role)
    db_user.last_login = now_local()
    db.commit()
    return {
        "token": token,
        "user": _build_user_info(db_user, db)
    }

@router.post("/auth/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise AppException(ERR_USERNAME_EXISTS, "用户名已存在", 409)
    if len(user.password) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码长度不足", 400)
    # 红线(交接说明 §六):管理员/老人/家属账号必须手工建号,接口自注册一律按志愿者处理
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

@router.get("/users/me")
def get_current_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppException(ERR_NOT_FOUND, "用户不存在", 404)
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "name": user.name,
        "avatar": user.avatar,
        "phone": user.phone,
        "role": user.role
    }

@router.put("/users/me")
def update_user(req: UserUpdate, authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppException(ERR_NOT_FOUND, "用户不存在", 404)
    if req.name is not None:
        user.name = req.name
    if req.avatar is not None:
        user.avatar = req.avatar
    if req.phone is not None:
        user.phone = req.phone
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "name": user.name,
        "avatar": user.avatar,
        "phone": user.phone
    }

@router.delete("/users/me")
def delete_user(authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppException(ERR_NOT_FOUND, "用户不存在", 404)
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}


class WxLogin(BaseModel):
    code: str
    nickName: Optional[str] = None
    avatarUrl: Optional[str] = None


@router.post("/auth/wx-login")
async def wx_login(data: WxLogin, db: Session = Depends(get_db)):
    WX_APPID = os.getenv("WX_APPID", "")
    WX_SECRET = os.getenv("WX_SECRET", "")
    if not WX_APPID or not WX_SECRET:
        raise AppException(5000, "微信登录未配置", 500)
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
        raise AppException(5000, f"微信登录失败: {wx_data.get('errmsg', '')}", 400)
    openid = wx_data["openid"]
    user = db.query(User).filter(User.openid == openid).first()
    if not user:
        # 契约示例用户名"微信用户";重名时追加序号保证唯一
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
    token = create_access_token(user.id, user.role)
    bound = len(user.parent_elders) > 0 if user.role == "children" else True
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "name": user.name,
            "avatar": user.avatar,
            "phone": user.phone,
            "openid": user.openid,
            "bound": bound
        }
    }


@router.post("/auth/bind-elder")
def bind_elder(
    req: BindElderRequest,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    db_user = db.query(User).filter(User.id == user_id).first()
    if not db_user:
        raise AppException(ERR_NOT_FOUND, "用户不存在", 404)
    # 契约(交接说明 §七):匹配须 name 与 phone 全等,不允许降级匹配
    elder = db.query(Elderly).filter(
        Elderly.name == req.name,
        Elderly.contact_info == req.phone
    ).first()
    if not elder:
        raise AppException(ERR_NOT_FOUND, "未找到匹配的老人档案,请核对姓名和电话", 404)
    if elder not in db_user.parent_elders:
        db_user.parent_elders.append(elder)
        db.commit()
    return {"elderId": elder.id, "elderName": elder.name}


@router.post("/auth/register-elder")
def register_elder(req: RegisterElderRequest, db: Session = Depends(get_db)):
    existing = db.query(Elderly).filter(Elderly.contact_info == req.phone).first()
    if existing:
        raise AppException(ERR_USERNAME_EXISTS, "该手机号已注册,请直接登录或更换手机号", 409)
    username = req.name
    counter = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{req.name}_{counter}"
        counter += 1
    db_user = User(
        username=username,
        password_hash=get_password_hash(req.phone),
        role=UserRole("elder"),
        name=req.name,
        phone=req.phone
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    elder = Elderly(
        name=req.name,
        age=0,
        gender=None,
        contact_info=req.phone,
        guardian_contact=req.emergencyContact,
        address="",
        created_by=db_user.id
    )
    db.add(elder)
    db.commit()
    token = create_access_token(db_user.id, db_user.role)
    return {
        "token": token,
        "user": {
            "id": db_user.id,
            "username": db_user.username,
            "role": "elder",
            "elderId": elder.id
        }
    }
