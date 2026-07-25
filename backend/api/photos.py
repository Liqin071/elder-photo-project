"""照片管理 API — 上传、查询、修改、删除"""
from fastapi import APIRouter, Depends, Query, Header, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, Field
import os
import uuid
from datetime import datetime
from io import BytesIO
from PIL import Image

from models.database import SessionLocal
from models.photo import Photo
from models.elderly import Elderly
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_FILE_TYPE, ERR_FILE_TOO_LARGE, ERR_ELDER_NOT_FOUND, ERR_NOT_FOUND, ERR_AUTH_REQUIRED

router = APIRouter(prefix="/api", tags=["照片管理"])


class ImageUpdate(BaseModel):
    note: Optional[str] = Field(None, description="备注内容")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"}
MAX_SIZE = 20 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user_id(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    return user_id


@router.post("/upload")
async def upload_photo(
    file: UploadFile = File(...),
    elderId: int = Form(...),
    note: Optional[str] = Form(None),
    uploaderRole: Optional[str] = Form(None),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_TYPES:
        raise AppException(ERR_FILE_TYPE, "文件类型不支持", 400)
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise AppException(ERR_FILE_TOO_LARGE, "超过20MB", 413)
    elder = db.query(Elderly).filter(Elderly.id == elderId).first()
    if not elder:
        raise AppException(ERR_ELDER_NOT_FOUND, "老人不存在", 404)

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    img_w, img_h, thumb_name = None, None, None
    try:
        img = Image.open(BytesIO(contents))
        img_w, img_h = img.size
        img.thumbnail((200, 200))
        thumb_name = f"thumb_{filename}"
        thumb_path = os.path.join(UPLOAD_DIR, "thumbs", thumb_name)
        os.makedirs(os.path.dirname(thumb_path), exist_ok=True)
        img.save(thumb_path, format=img.format or "JPEG")
    except:
        pass

    photo = Photo(
        elderly_id=elderId,
        volunteer_id=user_id,
        original_path=filename,
        thumbnail_path=f"thumbs/{thumb_name}" if thumb_name else None,
        note=note,
        file_size=len(contents),
        width=img_w,
        height=img_h,
        upload_time=datetime.utcnow()
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    return {
        "id": photo.id,
        "url": f"/uploads/{filename}",
        "thumbnailUrl": f"/uploads/thumbs/{thumb_name}" if thumb_name else None,
        "elderId": photo.elderly_id,
        "uploaderId": photo.volunteer_id,
        "uploaderRole": uploaderRole,
        "note": photo.note,
        "fileSize": photo.file_size,
        "width": photo.width,
        "height": photo.height,
        "format": ext,
        "createdAt": str(photo.upload_time)
    }


@router.get("/images")
def list_images(
    elder_id: Optional[int] = Query(None, alias="elderId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    sort_order: str = Query("desc", alias="sortOrder"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    query = db.query(Photo)
    if elder_id:
        query = query.filter(Photo.elderly_id == elder_id)
    if year:
        query = query.filter(Photo.upload_time >= datetime(year, 1, 1))
        if month:
            query = query.filter(Photo.upload_time < datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1))
    total = query.count()
    order = Photo.upload_time.desc() if sort_order == "desc" else Photo.upload_time.asc()
    photos = query.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [{
            "id": p.id, "url": f"/uploads/{p.original_path}",
            "thumbnailUrl": f"/uploads/{p.thumbnail_path}" if p.thumbnail_path else None,
            "note": p.note, "elderId": p.elderly_id,
            "elderName": p.elderly.name if p.elderly else None,
            "uploaderId": p.volunteer_id,
            "uploaderName": p.volunteer.name if p.volunteer else None,
            "uploaderRole": None, "fileSize": p.file_size, "width": p.width, "height": p.height,
            "createdAt": str(p.upload_time)
        } for p in photos],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.put("/images/{image_id}")
def update_image(
    image_id: int,
    req: ImageUpdate,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    if req.note is not None:
        p.note = req.note
    db.commit()
    return None


@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    filepath = os.path.join(UPLOAD_DIR, p.original_path)
    if os.path.exists(filepath):
        os.remove(filepath)
    db.delete(p)
    db.commit()
    return None
