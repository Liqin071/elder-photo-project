 
import hashlib
 
import bcrypt
 
from datetime import datetime, timedelta
 
from typing import Optional
 
from jose import JWTError, jwt
 
import os
 
from dotenv import load_dotenv
 

 
load_dotenv()
 

 
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
 
ALGORITHM = os.getenv("ALGORITHM", "HS256")
 
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
 
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
 
RESET_TOKEN_EXPIRE_MINUTES = int(os.getenv("RESET_TOKEN_EXPIRE_MINUTES", "60"))
 

 
def get_password_hash(password):
 
    prehashed = hashlib.sha256(password.encode()).hexdigest()
 
    return bcrypt.hashpw(prehashed.encode(), bcrypt.gensalt()).decode()
 

 
def verify_password(plain, hashed):
 
    prehashed = hashlib.sha256(plain.encode()).hexdigest()
 
    return bcrypt.checkpw(prehashed.encode(), hashed.encode())
 

 
def create_access_token(data, expires_delta=None):
 
    to_encode = data.copy()
 
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
 
    to_encode.update({"exp": expire, "type": "access", "iat": datetime.utcnow()})
 
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
 

 
def create_refresh_token(data):
 
    to_encode = data.copy()
 
    expire = datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
 
    to_encode.update({"exp": expire, "type": "refresh", "iat": datetime.utcnow()})
 
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
 

 
def verify_token(token):
 
    try:
 
        return int(jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM]).get("sub"))
 
    except:
 
        return None
 

 
def verify_refresh_token(token):
 
    try:
 
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
 
        if payload.get("type") != "refresh":
 
            return None
 
        return payload
 
    except JWTError:
 
        return None
 

 
def create_reset_token(user_id: int) -> str:
 
    to_encode = {
 
        "sub": str(user_id),
 
        "type": "reset",
 
        "exp": datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
 
        "iat": datetime.utcnow()
 
    }
 
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
 

 
def verify_reset_token(token: str) -> Optional[int]:
 
    try:
 
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
 
        if payload.get("type") != "reset":
 
            return None
 
        return int(payload.get("sub"))
 
    except:
 
        return None
 
 

 
from fastapi import Header, HTTPException
 

 
def get_current_user_id(authorization: str = Header(None)):
 
    """从 Authorization header 获取用户ID"""
 
    if not authorization or not authorization.startswith("Bearer "):
 
        raise HTTPException(status_code=401, detail="Invalid authorization header")
 
    token = authorization.split(" ")[1]
 
    user_id = verify_token(token)
 
    if not user_id:
 
        raise HTTPException(status_code=401, detail="Invalid or expired token")
 
    return user_id
 
