"""用户认证 API"""
from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from models.database import SessionLocal
from models.user import User, UserRole
from utils.auth import get_password_hash, verify_password, create_access_token, create_refresh_token, verify_token, verify_refresh_token
from utils.exceptions import AppException, ERR_AUTH_FAILED, ERR_AUTH_REQUIRED, ERR_USERNAME_EXISTS, ERR_PASSWORD_SHORT, ERR_NOT_FOUND
import httpx
import os
from datetime import datetime

router = APIRouter(prefix="/api", tags=["auth"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

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

@router.post("/auth/login")
def login(user: UserLogin, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.password_hash):
        raise AppException(ERR_AUTH_FAILED, "用户名或密码错误", 401)
    token = create_access_token(db_user.id, db_user.role)
    db_user.last_login = datetime.utcnow()
    db.commit()
    return {
        "token": token,
        "user": {
            "id": db_user.id,
            "username": db_user.username,
            "role": db_user.role,
            "name": db_user.name,
            "avatar": db_user.avatar,
            "phone": db_user.phone
        }
    }

@router.post("/auth/register")
def register(user: UserRegister, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == user.username).first()
    if db_user:
        raise AppException(ERR_USERNAME_EXISTS, "用户名已存在", 409)
    if len(user.password) < 6:
        raise AppException(ERR_PASSWORD_SHORT, "密码长度不足", 400)
    new_user = User(
        username=user.username,
        password_hash=get_password_hash(user.password),
        role=UserRole(user.role),
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
def update_user(request: dict, authorization: str = Header(None), db: Session = Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise AppException(ERR_NOT_FOUND, "用户不存在", 404)
    if "name" in request:
        user.name = request["name"]
    if "avatar" in request:
        user.avatar = request["avatar"]
    if "phone" in request:
        user.phone = request["phone"]
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
        username = f"wx_{openid[-8:]}"
        user = User(
            username=username,
            password_hash="",
            role=UserRole("children"),
            openid=openid,
            name=data.nickName,
            avatar=data.avatarUrl
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    token = create_access_token(user.id, user.role)
    return {
        "token": token,
        "user": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "name": user.name,
            "avatar": user.avatar,
            "phone": user.phone
        }
    }
