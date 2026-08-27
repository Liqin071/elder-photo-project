"""评论 API — 对齐小程序契约 + 权限矩阵"""
from fastapi import APIRouter, Depends, Query, Header, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, Field
import os
import json
import uuid

from models.comment import Comment
from models.photo import Photo
from models.elderly import Elderly
from models.notification import Notification
from utils.permissions import get_db, get_current_user, is_admin, deny, elder_of_user, check_elder_access
from utils.exceptions import AppException, ERR_NOT_FOUND, ERR_NO_PERMISSION
from utils.timefmt import fmt_dt

router = APIRouter(prefix="/api", tags=["评论"])


class CommentCreate(BaseModel):
    targetType: str = Field(..., description="目标类型：image / elder")
    targetId: int = Field(..., description="目标ID")
    content: str = Field(..., description="评论内容")
    contentType: str = Field("text", description="内容类型：text / voice")

VOICE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "voices")
os.makedirs(VOICE_DIR, exist_ok=True)


def _build_full_url(request, path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = str(request.base_url).rstrip("/")
    return base + path


def _comment_to_dict(c, request, current_user):
    author = c.author
    author_name = author.name if author else (author.username if author else "匿名")
    return {
        "id": c.id,
        "targetType": c.target_type,
        "targetId": c.target_id,
        "content": c.content or "",
        "contentType": c.content_type,
        "voiceUrl": _build_full_url(request, c.voice_url) if c.voice_url else None,
        "voiceDuration": c.voice_duration,
        "authorId": c.author_id,
        "authorName": author_name,
        "authorAvatar": author.avatar if author else None,
        "authorRole": author.role if author else None,
        "createdAt": fmt_dt(c.created_at),
        "canDelete": bool(current_user) and c.author_id == current_user.id
    }


def _get_target_photo(db, target_type, target_id):
    """解析留言目标照片;非影像目标(如 elder)返回 None(仅要求登录)"""
    if target_type in ("image", "photo"):
        return db.query(Photo).filter(Photo.id == target_id).first()
    return None


def _check_target_access(db, user, photo):
    """留言可见圈:elder ●(自己的照片) / children ●(绑定的老人) / volunteer ●(分配的老人);admin ○"""
    if not photo:
        return
    if is_admin(user):
        deny()
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != photo.elderly_id:
            deny()
    else:
        check_elder_access(db, user, photo.elderly_id)


def _notify_comment(db, author, comment, photo):
    """留言后通知该老人绑定的所有家属(type=comment, metadata.elderId 供跳转)"""
    if not photo or not photo.elderly:
        return
    elder = photo.elderly
    children = elder.children
    if not children:
        return
    author_name = author.name or author.username
    for child in children:
        if child.id == author.id:
            continue
        db.add(Notification(
            user_id=child.id,
            type="comment",
            title="照片收到新留言",
            content=f"{author_name} 回复了照片留言",
            metadata_info=json.dumps({"elderId": elder.id}),
        ))
    db.commit()


@router.get("/comments")
def list_comments(
    request: Request,
    target_type: str = Query(..., alias="targetType"),
    target_id: int = Query(..., alias="targetId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    photo = _get_target_photo(db, target_type, target_id)
    if photo is None and target_type in ("image", "photo"):
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    _check_target_access(db, user, photo)
    q = db.query(Comment).filter(
        Comment.target_type == target_type,
        Comment.target_id == target_id
    ).order_by(Comment.created_at.asc())
    total = q.count()
    comments = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_comment_to_dict(c, request, user) for c in comments],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.post("/comments", status_code=201)
def create_comment(
    request: Request,
    req: CommentCreate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    photo = _get_target_photo(db, req.targetType, req.targetId)
    if photo is None and req.targetType in ("image", "photo"):
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    _check_target_access(db, user, photo)
    content = (req.content or "").strip()
    if not content:
        raise AppException(1003, "留言内容不能为空", 400)
    c = Comment(
        target_type=req.targetType,
        target_id=req.targetId,
        content=content,
        content_type="text",
        author_id=user.id,
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    _notify_comment(db, user, c, photo)
    return _comment_to_dict(c, request, user)


@router.post("/comments/voice", status_code=201)
async def create_voice_comment(
    request: Request,
    audio: UploadFile = File(...),
    targetType: str = Form(...),
    targetId: int = Form(...),
    duration: Optional[int] = Form(None),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    photo = _get_target_photo(db, targetType, targetId)
    if photo is None and targetType in ("image", "photo"):
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    _check_target_access(db, user, photo)
    # 小程序录音产出 mp3,web 端是 webm(契约 2.9:两者都要接受)
    ext = audio.filename.rsplit(".", 1)[-1].lower() if "." in audio.filename else "mp3"
    if ext not in ("mp3", "webm", "m4a", "aac", "wav", "amr"):
        ext = "mp3"
    filename = f"voice_{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(VOICE_DIR, filename)
    contents = await audio.read()
    with open(filepath, "wb") as f:
        f.write(contents)

    c = Comment(
        target_type=targetType,
        target_id=targetId,
        content_type="voice",
        content="",
        voice_url=f"/uploads/voices/{filename}",
        voice_duration=duration,
        author_id=user.id
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    _notify_comment(db, user, c, photo)
    return _comment_to_dict(c, request, user)


@router.delete("/comments/{comment_id}")
def delete_comment(
    comment_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    c = db.query(Comment).filter(Comment.id == comment_id).first()
    if not c:
        raise AppException(ERR_NOT_FOUND, "不存在", 404)
    if c.author_id != user.id:
        raise AppException(ERR_NO_PERMISSION, "无权限操作", 403)
    if c.voice_url:
        vp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), c.voice_url.lstrip("/"))
        if os.path.exists(vp):
            os.remove(vp)
    db.delete(c)
    db.commit()
    return None
