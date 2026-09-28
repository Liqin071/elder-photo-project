"""通知写入与级联清理 — 通知矩阵硬契约(API 文档 §2.11,2026-09-12)

矩阵(唯一权威定义见 docs/API文档.md §2.11,此处为实现):
- 上传:上传者=elder → 通知全部绑定家属;上传者=children/volunteer → 通知老人 user + 全部绑定家属(除上传者本人)
- 留言(文字/语音):作者=children/volunteer → 通知老人 user;作者=elder → 通知全部绑定家属
- 绑定(§1.3/1.5):通知老人 user(type=system)
- 删照片:按删除者角色反向通知(elder 删→家属;children/volunteer 删→老人;admin 删→两边都收),type=system,metadata 不带 imageId
- 删留言:不产生新通知,**清理**该 commentId 的全部未读通知
- 删照片级联:①删该照片全部 comments ②删所有 metadata.imageId 指向它的通知(含已读,避免死链)③写删除通知

metadata 规范:`{elderId 必带, imageId? 直达照片详情, commentId? 删留言级联清理}`
"""
import json
from sqlalchemy.orm import Session
from models.notification import Notification
from utils.permissions import find_elder_user

META_SEP = (",", ":")


def _meta(**kwargs):
    """紧凑 JSON(便于 LIKE 预筛 + 精确比对)"""
    return json.dumps({k: v for k, v in kwargs.items() if v is not None}, separators=META_SEP)


def _add(db, user_id, ntype, title, content, metadata):
    db.add(Notification(
        user_id=user_id,
        type=ntype,
        title=title,
        content=content,
        metadata_info=metadata,
    ))


def _family_users(elder):
    """该老人全部绑定家属(users 列表)"""
    return list(elder.children) if elder and elder.children else []


def _display_name(user):
    if not user:
        return "有人"
    return user.name or user.username or "有人"


# ---------------- 绑定 ----------------
def notify_bind_elder(db: Session, elder, child_name: str):
    """家属绑定成功后给老人账号写一条 type=system 通知(老人端铃铛可见)"""
    target = find_elder_user(db, elder)
    if not target:
        return
    _add(db, target.id, "system", "新家属绑定", f"家属 {child_name} 已绑定到您的档案",
         _meta(elderId=elder.id))
    db.commit()


# ---------------- 上传 ----------------
def notify_upload(db: Session, uploader, elder, image_id, count=1):
    """上传照片后的通知矩阵"""
    if not elder:
        return
    family = _family_users(elder)
    name = _display_name(uploader)
    content = f"{name} 上传了 {count} 张新照片"
    if uploader and uploader.role == "elder":
        # 上传者=老人 → 只通知绑定家属
        for c in family:
            if c.id == uploader.id:
                continue
            _add(db, c.id, "image", f"{elder.name}有新的照片", content,
                 _meta(elderId=elder.id, imageId=image_id))
    else:
        # 上传者=家属/志愿者 → 通知老人本人 + 绑定家属(除上传者)
        target = find_elder_user(db, elder)
        if target and (not uploader or target.id != uploader.id):
            _add(db, target.id, "image", "您有新的照片", content,
                 _meta(elderId=elder.id, imageId=image_id))
        for c in family:
            if uploader and c.id == uploader.id:
                continue
            _add(db, c.id, "image", f"{elder.name}有新的照片", content,
                 _meta(elderId=elder.id, imageId=image_id))
    db.commit()


# ---------------- 留言 ----------------
def notify_comment(db: Session, author, elder, image_id, comment_id, content_type, content):
    """留言(文字/语音)后的通知矩阵"""
    if not elder:
        return
    summary = "[语音留言]" if content_type == "voice" else (content or "")[:50]
    name = _display_name(author)
    if author and author.role == "elder":
        # 作者=老人 → 通知全部绑定家属
        for c in _family_users(elder):
            if c.id == author.id:
                continue
            _add(db, c.id, "comment", f"{elder.name} 给照片留言了", summary,
                 _meta(elderId=elder.id, imageId=image_id, commentId=comment_id))
    else:
        # 作者=家属/志愿者 → 通知老人本人
        target = find_elder_user(db, elder)
        if target and (not author or target.id != author.id):
            _add(db, target.id, "comment", f"{name} 给您的照片留言了", summary,
                 _meta(elderId=elder.id, imageId=image_id, commentId=comment_id))
    db.commit()


# ---------------- 删除 ----------------
def notify_image_deleted(db: Session, deleter, elder):
    """删照片后的系统通知(metadata 不带 imageId:照片已不存在,带了就是死链)"""
    if not elder:
        return
    name = _display_name(deleter)
    title = "照片已删除"
    content = f"{name} 删除了一张照片(留言一并移除)"
    meta = _meta(elderId=elder.id)
    role = deleter.role if deleter else None
    family = _family_users(elder)
    target = find_elder_user(db, elder)
    if role == "elder":
        recipients = [c.id for c in family if not deleter or c.id != deleter.id]
    elif role == "admin":
        recipients = [c.id for c in family]
        if target:
            recipients.append(target.id)
    else:  # children / volunteer
        recipients = [target.id] if target and (not deleter or target.id != deleter.id) else []
    for uid in set(recipients):
        _add(db, uid, "system", title, content, meta)
    db.commit()


# ---------------- 级联清理 ----------------
def _iter_notifications_with_key(db: Session, key: str):
    """预筛(metadata_info LIKE)后在 Python 里精确比对,避免依赖数据库 JSON 函数"""
    rows = db.query(Notification).filter(Notification.metadata_info.like(f'%"{key}"%')).all()
    for n in rows:
        try:
            meta = json.loads(n.metadata_info or "{}")
        except Exception:
            meta = {}
        yield n, meta


def cleanup_comment_notifications(db: Session, comment_id: int):
    """删留言:清理该留言的全部**未读**通知(所有接收人)"""
    removed = 0
    for n, meta in _iter_notifications_with_key(db, "commentId"):
        if meta.get("commentId") == comment_id and not n.is_read:
            db.delete(n)
            removed += 1
    if removed:
        db.commit()
    return removed


def cleanup_image_notifications(db: Session, image_id: int):
    """删照片:清理所有引用该照片的通知(含已读——照片没了,通知即死链)"""
    removed = 0
    for n, meta in _iter_notifications_with_key(db, "imageId"):
        if meta.get("imageId") == image_id:
            db.delete(n)
            removed += 1
    if removed:
        db.commit()
    return removed


# ---------------- 未读口径(实时) ----------------
def unread_messages_count(db: Session, elder):
    """
    家属端家人卡"未读留言"实时口径(API 文档 §2.1):
    = 该老人名下照片上、作者非老人本人、且 elder_read_at 为空的**现存** comments 行数。
    必须实时 COUNT,禁止累加计数器(删留言/已读/删照片都要立即反映)。
    """
    from models.comment import Comment
    from models.photo import Photo

    if not elder:
        return 0
    photo_ids = [r[0] for r in db.query(Photo.id).filter(Photo.elderly_id == elder.id).all()]
    if not photo_ids:
        return 0
    q = db.query(Comment).filter(
        Comment.target_type.in_(("image", "photo")),
        Comment.target_id.in_(photo_ids),
        Comment.elder_read_at.is_(None),
    )
    elder_user = find_elder_user(db, elder)
    if elder_user:
        q = q.filter(Comment.author_id != elder_user.id)
    return q.count()


def mark_comments_read(db: Session, elder, image_id: int):
    """老人已读回执:该照片下全部留言 elder_read_at 置当前时间(幂等)"""
    from models.comment import Comment
    from utils.timefmt import now_local
    rows = db.query(Comment).filter(
        Comment.target_type.in_(("image", "photo")),
        Comment.target_id == image_id,
        Comment.elder_read_at.is_(None),
    ).all()
    for c in rows:
        c.elder_read_at = now_local()
    if rows:
        db.commit()
    return len(rows)
