"""评论 API"""
from fastapi import APIRouter, Depends, Query, Header, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
import os
import uuid

from models.database import SessionLocal
from models.comment import Comment
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_NO_PERMISSION, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["评论"])

VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "voices")
os.makedirs(VOICE_DIR, exist_ok=True)


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
    request: dict,
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    c = Comment(
        target_type=request["targetType"],
        target_id=request["targetId"],
        content=request.get("content", ""),
        content_type=request.get("contentType", "text"), author_id=uid,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
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
