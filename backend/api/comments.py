"""评论 API"""
from fastapi import APIRouter, Depends, HTTPException, Query, Header, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
import os
import uuid

from models.database import SessionLocal
from models.comment import Comment
from utils.auth import verify_token

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
        raise HTTPException(status_code=401, detail="未登录")
    uid = verify_token(authorization.split(" ")[1])
    if not uid:
        raise HTTPException(status_code=401, detail="token过期")
    return uid


@router.get("/comments")
def list_comments(
    target_type: str = Query(..., alias="targetType"),
    target_id: int = Query(..., alias="targetId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
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
            "target_type": c.target_type,
            "target_id": c.target_id,
            "content": c.content,
            "content_type": c.content_type,
            "voice_url": c.voice_url,
            "voice_duration": c.voice_duration,
            "author_id": c.author_id,
            "author_name": c.author.name if c.author else None,
            "author_avatar": c.author.avatar if c.author else None,
            "author_role": c.author.role if c.author else None,
            "created_at": str(c.created_at),
            "can_delete": c.author_id == uid
        } for c in comments],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
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
        content_type=request.get("contentType", "text")
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {
        "id": c.id,
        "target_type": c.target_type,
        "target_id": c.target_id,
        "content": c.content,
        "content_type": c.content_type,
        "voice_url": c.voice_url,
        "voice_duration": c.voice_duration,
        "author_id": c.author_id,
        "author_name": c.author.name if c.author else None,
        "author_avatar": c.author.avatar if c.author else None,
        "author_role": c.author.role if c.author else None,
        "created_at": str(c.created_at),
        "can_delete": True
    }


@router.post("/comments/voice", status_code=201)
async def create_voice_comment(
    audio: UploadFile = File(...),
    target_type: str = Form(..., alias="targetType"),
    target_id: int = Form(..., alias="targetId"),
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
        target_type=target_type,
        target_id=target_id,
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
        "target_type": c.target_type,
        "target_id": c.target_id,
        "content": None,
        "content_type": "voice",
        "voice_url": c.voice_url,
        "voice_duration": c.voice_duration,
        "author_id": c.author_id,
        "author_name": c.author.name if c.author else None,
        "author_avatar": c.author.avatar if c.author else None,
        "author_role": c.author.role if c.author else None,
        "created_at": str(c.created_at),
        "can_delete": True
    }


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    uid: int = Depends(get_uid),
    db: Session = Depends(get_db)
):
    c = db.query(Comment).filter(Comment.id == comment_id).first()
    if not c:
        raise HTTPException(status_code=404, detail="不存在")
    if c.author_id != uid:
        raise HTTPException(status_code=403, detail="无权限")
    if c.voice_url:
        vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), c.voice_url.lstrip("/"))
        if os.path.exists(vp):
            os.remove(vp)
    db.delete(c)
    db.commit()
    return None
