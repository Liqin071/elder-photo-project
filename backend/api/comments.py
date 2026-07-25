"""评论 API"""
from fastapi import APIRouter, Depends, Query, Header, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from pydantic import BaseModel, Field
import os
import uuid

from models.database import SessionLocal
from models.comment import Comment
from models.photo import Photo
from models.elderly import Elderly
from models.notification import Notification
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_NO_PERMISSION, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["评论"])


class CommentCreate(BaseModel):
    targetType: str = Field(..., description="目标类型：photo / elder")
    targetId: int = Field(..., description="目标ID")
    content: str = Field(..., description="评论内容")
    contentType: str = Field("text", description="内容类型：text / voice")

VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "voices")
os.makedirs(VOICE_DIR, exist_ok=True)


def _notify_comment(db, author_id: int, author_name: str, target_type: str, target_id: int):
    """评论后通知目标所有者"""
    target_user_id = None
    target_title = ""
    if target_type == "photo":
        p = db.query(Photo).filter(Photo.id == target_id).first()
        if p:
            target_user_id = p.volunteer_id
            target_title = f"照片（{p.elderly.name if p.elderly else '未知'}）"
    elif target_type == "elder":
        e = db.query(Elderly).filter(Elderly.id == target_id).first()
        if e:
            target_user_id = e.created_by
            target_title = f"老人档案（{e.name}）"
    if target_user_id and target_user_id != author_id:
        notif = Notification(
            user_id=target_user_id,
            type="comment",
            title="新评论",
            content=f"{author_name} 评论了你的{target_title}",
        )
        db.add(notif)
        db.commit()


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


@router.get("/comments")
def list_comments(
    target_type: str = Query(..., alias="targetType"),
    target_id: int = Query(..., alias="targetId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    q = db.query(Comment).filter(
        Comment.target_type == target_type,
        Comment.target_id == target_id
    ).order_by(Comment.created_at.desc())
    total = q.count()
    comments = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [{
            "id": c.id,
            "targetType": c.target_type,
            "targetId": c.target_id,
            "content": c.content,
            "contentType": c.content_type,
            "voiceUrl": c.voice_url,
            "voiceDuration": c.voice_duration,
            "authorId": c.author_id,
            "authorName": c.author.name if c.author else None,
            "authorAvatar": c.author.avatar if c.author else None,
            "authorRole": c.author.role if c.author else None,
            "createdAt": str(c.created_at),
            "canDelete": c.author_id == uid
        } for c in comments],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.post("/comments", status_code=201)
def create_comment(
    req: CommentCreate,
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    c = Comment(
        target_type=req.targetType,
        target_id=req.targetId,
        content=req.content,
        content_type=req.contentType, author_id=uid,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    _notify_comment(db, uid, c.author.name or "匿名", c.target_type, c.target_id)
    return {
        "id": c.id,
        "targetType": c.target_type,
        "targetId": c.target_id,
        "content": c.content,
        "contentType": c.content_type,
        "voiceUrl": c.voice_url,
        "voiceDuration": c.voice_duration,
        "authorId": c.author_id,
        "authorName": c.author.name if c.author else None,
        "authorAvatar": c.author.avatar if c.author else None,
        "authorRole": c.author.role if c.author else None,
        "createdAt": str(c.created_at),
        "canDelete": True
    }


@router.post("/comments/voice", status_code=201)
async def create_voice_comment(
    audio: UploadFile = File(...),
    targetType: str = Form(...),
    targetId: int = Form(...),
    duration: Optional[int] = Form(None),
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    ext = audio.filename.rsplit(".", 1)[-1] if "." in audio.filename else "webm"
    filename = f"voice_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(VOICE_DIR, filename)
    contents = await audio.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    c = Comment(
        target_type=targetType,
        target_id=targetId,
        content_type="voice",
        voice_url=f"/uploads/voices/{filename}",
        voice_duration=duration,
        author_id=uid
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    _notify_comment(db, uid, c.author.name or "匿名", c.target_type, c.target_id)
    return {
        "id": c.id,
        "targetType": c.target_type,
        "targetId": c.target_id,
        "content": None,
        "contentType": "voice",
        "voiceUrl": c.voice_url,
        "voiceDuration": c.voice_duration,
        "authorId": c.author_id,
        "authorName": c.author.name if c.author else None,
        "authorAvatar": c.author.avatar if c.author else None,
        "authorRole": c.author.role if c.author else None,
        "createdAt": str(c.created_at),
        "canDelete": True
    }


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    c = db.query(Comment).filter(Comment.id == comment_id).first()
    if not c:
        raise AppException(ERR_NOT_FOUND, "不存在", 404)
    if c.author_id != uid:
        raise AppException(ERR_NO_PERMISSION, "无权限操作", 403)
    if c.voice_url:
        vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), c.voice_url.lstrip("/"))
        if os.path.exists(vp):
            os.remove(vp)
    db.delete(c)
    db.commit()
    return None
