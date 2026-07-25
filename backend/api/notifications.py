"""通知 API"""
from fastapi import APIRouter, Depends, Query, Header
from sqlalchemy.orm import Session
from typing import Optional
import json

from models.database import SessionLocal
from models.notification import Notification
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["通知"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_uid(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    uid = verify_token(authorization.split(" ")[1])
    if not uid:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    return uid


def _notif_to_dict(n):
    meta = None
    if n.metadata_info:
        try:
            meta = json.loads(n.metadata_info)
        except:
            pass
    return {
        "id": n.id, "type": n.type, "title": n.title,
        "content": n.content, "isRead": n.is_read,
        "metadata": meta, "createdAt": str(n.created_at)
    }


@router.get("/notifications")
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    is_read: Optional[bool] = Query(None, alias="isRead"),
    ntype: Optional[str] = Query(None, alias="type"),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    q = db.query(Notification).filter(
        Notification.user_id == uid
    ).order_by(Notification.created_at.desc())
    if is_read is not None:
        q = q.filter(Notification.is_read == is_read)
    if ntype:
        q = q.filter(Notification.type == ntype)
    total = q.count()
    notifs = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_notif_to_dict(n) for n in notifs],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.get("/notifications/unread-count")
def unread_count(
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    cnt = db.query(Notification).filter(
        Notification.user_id == uid,
        Notification.is_read == False
    ).count()
    return {"unreadCount": cnt}


@router.put("/notifications/{notif_id}/read")
def mark_read(
    notif_id: int,
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    n = db.query(Notification).filter(
        Notification.id == notif_id,
        Notification.user_id == uid
    ).first()
    if not n:
        raise AppException(ERR_NOT_FOUND, "不存在", 404)
    n.is_read = True
    db.commit()
    return None


@router.put("/notifications/read-all")
def mark_all_read(
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    db.query(Notification).filter(
        Notification.user_id == uid,
        Notification.is_read == False
    ).update({"is_read": True})
    db.commit()
    return None
