"""认证工具函数"""
import hashlib
import bcrypt
import jwt
from datetime import datetime, timedelta
from fastapi import HTTPException, Header
from sqlalchemy.orm import Session
from models.user import User

SECRET_KEY = "your-secret-key-here-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_SECONDS = 7200
REFRESH_TOKEN_EXPIRE_DAYS = 7

def pre_hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_password_hash(password):
    pre_hashed = pre_hash_password(password)
    return bcrypt.hashpw(pre_hashed.encode(), bcrypt.gensalt()).decode()

def verify_password(password, hashed_password):
    pre_hashed = pre_hash_password(password)
    return bcrypt.checkpw(pre_hashed.encode(), hashed_password.encode())

def create_access_token(user_id, user_role):
    to_encode = {"userId": user_id, "role": user_role, "type": "access", "iat": datetime.utcnow()}
    expire = datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_EXPIRE_SECONDS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(user_id):
    to_encode = {"userId": user_id, "type": "refresh", "iat": datetime.utcnow()}
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "access":
            return None
        return payload.get("userId")
    except:
        return None

def verify_refresh_token(token):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("type") != "refresh":
            return None
        return payload
    except:
        return None

def get_current_user(authorization: str = Header(None), db: Session = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if db:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user
    return user_id
