"""照片管理 API — 对齐小程序前端契约 + 权限矩阵(交接说明 §六)"""
from fastapi import APIRouter, Depends, Query, Header, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel, Field
import os
import json
import uuid
from datetime import datetime
from io import BytesIO
from PIL import Image

from models.photo import Photo
from models.elderly import Elderly
from models.notification import Notification
from utils.permissions import get_db, get_current_user, is_admin, deny, elder_of_user, check_elder_access, get_elder_relationship
from utils.exceptions import AppException, ERR_FILE_TYPE, ERR_FILE_TOO_LARGE, ERR_ELDER_NOT_FOUND, ERR_NOT_FOUND
from utils.timefmt import fmt_dt, now_local

router = APIRouter(prefix="/api", tags=["照片管理"])


class ImageUpdate(BaseModel):
    note: Optional[str] = Field(None, description="备注内容")

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "application/octet-stream"}
ALLOWED_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
MAX_SIZE = 20 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)


def _build_full_url(request, path):
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    base = str(request.base_url).rstrip("/")
    return base + path


def _photo_to_dict(p, request, user, db):
    uploader_name = None
    if p.volunteer:
        uploader_name = p.volunteer.name or p.volunteer.username
    # canDelete 接口层计算、不落库(交接说明 §六):
    # admin 任意;elder 可删名下全部(含志愿者代拍);children 仅自己上传的;volunteer 无删除权
    can_delete = False
    if user:
        if user.role == "admin":
            can_delete = True
        elif user.role == "elder":
            own = elder_of_user(db, user)
            if own and own.id == p.elderly_id:
                can_delete = True
        elif user.role == "children":
            if p.volunteer_id == user.id:
                can_delete = True
    url = _build_full_url(request, f"/uploads/{p.original_path}")
    thumb_path = f"/uploads/{p.thumbnail_path}" if p.thumbnail_path else f"/uploads/{p.original_path}"
    thumb_url = _build_full_url(request, thumb_path)
    return {
        "id": p.id,
        "url": url,
        "thumbnailUrl": thumb_url,
        "note": p.note,
        "elderId": p.elderly_id,
        "elderName": p.elderly.name if p.elderly else None,
        "uploaderId": p.volunteer_id,
        "uploaderName": uploader_name,
        "uploaderRole": p.volunteer.role if p.volunteer else None,
        "fileSize": p.file_size,
        "width": p.width,
        "height": p.height,
        "createdAt": fmt_dt(p.upload_time),
        "canDelete": can_delete
    }


def _check_image_scope(db, user, elder_id):
    """影像可见圈校验:elder 仅自己 / children 仅绑定;admin、volunteer 拒绝(矩阵 ○)"""
    if is_admin(user) or user.role == "volunteer":
        deny()
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own:
            deny()
        if elder_id is None:
            return own.id
        if elder_id != own.id:
            deny()
        return own.id
    # children
    if elder_id is None:
        deny()
    check_elder_access(db, user, elder_id)
    return elder_id


def _notify_new_photos(db, uploader, elder, count):
    """上传后通知该老人绑定的所有家属(type=image, metadata.elderId 供前端跳转)"""
    children = elder.children if elder else []
    if not children:
        return
    uploader_name = uploader.name or uploader.username
    for child in children:
        if child.id == uploader.id:
            continue
        rel = get_elder_relationship(db, child.id, elder.id)
        if rel in ("母亲", "妈妈"):
            title = "妈妈有新的照片"
        elif rel in ("父亲", "爸爸"):
            title = "爸爸有新的照片"
        else:
            title = f"{elder.name}有新的照片"
        content = f"{uploader_name} 为 {elder.name} 上传了 {count} 张新照片"
        db.add(Notification(
            user_id=child.id,
            type="image",
            title=title,
            content=content,
            metadata_info=json.dumps({"elderId": elder.id}),
        ))
    db.commit()


@router.post("/upload")
async def upload_photo(
    request: Request,
    file: UploadFile = File(...),
    elderId: int = Form(...),
    note: Optional[str] = Form(None),
    uploaderRole: Optional[str] = Form(None),
    subscribeGranted: Optional[str] = Form(None),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if is_admin(user):
        deny()  # 矩阵:admin 无上传权(管理端无上传 UI)
    elder = db.query(Elderly).filter(Elderly.id == elderId).first()
    if not elder:
        raise AppException(ERR_ELDER_NOT_FOUND, "老人不存在", 404)
    check_elder_access(db, user, elderId)  # elder 仅自己 / children 仅绑定 / volunteer 仅分配
    # uploaderId 由 token 解出,身份以 token 为准(交接说明 §六.2);uploaderRole 参数仅作展示一致性参考

    # 微信开发者工具/部分机型可能以 application/octet-stream 上报,内容类型或扩展名任一合法即可
    ext_check = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if (file.content_type or "").lower() not in ALLOWED_TYPES and ext_check not in ALLOWED_EXTS:
        raise AppException(ERR_FILE_TYPE, "文件类型不支持", 400)
    contents = await file.read()
    if len(contents) > MAX_SIZE:
        raise AppException(ERR_FILE_TOO_LARGE, "超过20MB", 413)

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
        volunteer_id=user.id,
        original_path=filename,
        thumbnail_path=f"thumbs/{thumb_name}" if thumb_name else None,
        note=(note and note.strip()) or "暂无备注",
        file_size=len(contents),
        width=img_w,
        height=img_h,
        upload_time=now_local()
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    # 站内通知:推给该老人绑定的所有家属(type=image)
    _notify_new_photos(db, user, elder, 1)

    result = _photo_to_dict(photo, request, user, db)
    result.pop("canDelete", None)  # 上传响应不含 canDelete(契约 2.6)
    return result


@router.get("/images")
def list_images(
    request: Request,
    elder_id: Optional[int] = Query(None, alias="elderId"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=1000, alias="pageSize"),  # 契约:影像详情按 pageSize=999 全量反查
    year: Optional[int] = None,
    month: Optional[int] = None,
    sort_order: str = Query("desc", alias="sortOrder"),
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    eid = _check_image_scope(db, user, elder_id)
    query = db.query(Photo)
    if eid is not None:
        query = query.filter(Photo.elderly_id == eid)
    if year:
        query = query.filter(Photo.upload_time >= datetime(year, 1, 1))
        if month:
            end_month = month + 1
            end_year = year
            if end_month > 12:
                end_month = 1
                end_year = year + 1
            query = query.filter(Photo.upload_time < datetime(end_year, end_month, 1))
    total = query.count()
    order = Photo.upload_time.desc() if sort_order == "desc" else Photo.upload_time.asc()
    photos = query.order_by(order).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_photo_to_dict(p, request, user, db) for p in photos],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size
    }


@router.get("/images/{image_id}")
def get_image(
    image_id: int,
    request: Request,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """单图反查(契约 §6 建议接口;影像详情按 id 取图)"""
    user = get_current_user(authorization, db)
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    _check_image_scope(db, user, p.elderly_id)
    return _photo_to_dict(p, request, user, db)


@router.put("/images/{image_id}")
def update_image(
    image_id: int,
    req: ImageUpdate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    # 矩阵:改备注 elder ●(自己的照片) / children ●(绑定老人的照片) / volunteer、admin ○
    if user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != p.elderly_id:
            deny()
    elif user.role == "children":
        check_elder_access(db, user, p.elderly_id)
    else:
        deny()
    if req.note is not None:
        p.note = req.note
        db.commit()
    return None


@router.delete("/images/{image_id}")
def delete_image(
    image_id: int,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    p = db.query(Photo).filter(Photo.id == image_id).first()
    if not p:
        raise AppException(ERR_NOT_FOUND, "资源不存在", 404)
    # 矩阵:admin ●(任意) / elder ●(仅自己名下,含志愿者代拍) / children ●(仅自己上传的) / volunteer ○
    if user.role == "admin":
        pass
    elif user.role == "elder":
        own = elder_of_user(db, user)
        if not own or own.id != p.elderly_id:
            deny()
    elif user.role == "children":
        if p.volunteer_id != user.id:
            deny()
    else:
        deny()
    filepath = os.path.join(UPLOAD_DIR, p.original_path)
    if os.path.exists(filepath):
        os.remove(filepath)
    if p.thumbnail_path:
        thumb_path = os.path.join(UPLOAD_DIR, p.thumbnail_path)
        if os.path.exists(thumb_path):
            os.remove(thumb_path)
    db.delete(p)
    db.commit()
    return None
