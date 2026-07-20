"""用户认证 API"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional
from models.database import SessionLocal
from models.user import User, UserRole
from utils.auth import get_password_hash, verify_password, create_access_token, create_refresh_token, verify_token, verify_refresh_token
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
        raise HTTPException(status_code=401, detail="用户名或密码错误")
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
        raise HTTPException(status_code=409, detail="用户名已存在")
    if len(user.password) < 6:
        raise HTTPException(status_code=400, detail="密码长度不足")
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
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
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
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user)
    db.commit()
    return {"message": "User deleted successfully"}
