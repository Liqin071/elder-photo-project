"""照片管理 API — 上传、查询、修改、删除"""
from fastapi import APIRouter, Depends, HTTPException, Query, Header, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
import os
import uuid
from datetime import datetime

from models.database import SessionLocal
from models.photo import Photo
from models.elderly import Elderly
from utils.auth import verify_token

router = APIRouter(prefix="/api", tags=["照片管理"])

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
        raise HTTPException(status_code=401, detail="未登录或token已过期")
    token = authorization.split(" ")[1]
    user_id = verify_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="未登录或token已过期")
    return user_id


@router.post("/upload")
async def upload_photo(
    file: UploadFile = File(...),
    elder_id: int = Form(..., alias="elderId"),
    note: Optional[str] = Form(None),
    uploader_role: Optional[str] = Form(None, alias="uploaderRole"),
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="文件类型不支持")
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="超过20MB")
    elder = db.query(Elderly).filter(Elderly.id == elder_id).first()
    if not elder:
        raise HTTPException(status_code=404, detail="老人不存在")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else "jpg"
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(contents)

    photo = Photo(
        elderly_id=elder_id,
        volunteer_id=user_id,
        original_path=filename,
        note=note,
        upload_time=datetime.utcnow()
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    return {
        "id": photo.id,
        "url": f"/uploads/{filename}",
        "thumbnail_url": None,
        "elder_id": photo.elderly_id,
        "uploader_id": photo.volunteer_id,
        "uploader_role": uploader_role,
        "note": photo.note,
        "file_size": len(contents),
        "width": None,
        "height": None,
        "format": ext,
        "created_at": str(photo.upload_time)
    }


@router.get("/images")
def list_images(
    elder_id: Optional[int] = Query(None, alias="elderId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    year: Optional[int] = None,
    month: Optional[int] = None,
    sort_order: str = "desc",
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
            "thumbnail_url": f"/uploads/{p.thumbnail_path}" if p.thumbnail_path else None,
            "note": p.note, "elder_id": p.elderly_id,
            "elder_name": p.elderly.name if p.elderly else None,
            "uploader_id": p.volunteer_id,
            "uploader_name": p.volunteer.name if p.volunteer else None,
            "uploader_role": None, "file_size": None, "width": None, "height": None,
            "created_at": str(p.upload_time)
        } for p in photos],
        "total": total, "page": page, "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size
    }


@router.put("/images/{image_id}")
def update_image(
    image_id: int,
    request: dict,
    user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db)
):
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="资源不存在")
    if "note" in request:
        p.note = request["note"]
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
        raise HTTPException(status_code=404, detail="资源不存在")
    filepath = os.path.join(UPLOAD_DIR, p.original_path)
    if os.path.exists(filepath):
        os.remove(filepath)
    db.delete(p)
    db.commit()
    return None
