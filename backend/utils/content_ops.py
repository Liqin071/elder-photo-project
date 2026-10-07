"""内容级联删除工具 — 被「删照片/删留言」端点与「举报处置」共用,保证行为一致。

删照片三件套(契约硬要求):
  ① 级联删除该照片下所有留言(语音文件一并清理)
  ② 清除所有引用该照片的通知(含已读,防死链)
  ③ 按通知矩阵写 system 删除通知
删留言:清理语音文件 + 清除该留言的未读通知
"""
import os

from models.comment import Comment
from utils.notify import cleanup_comment_notifications, cleanup_image_notifications, notify_image_deleted
from utils.timefmt import now_local

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")


def _remove_file(rel_path: str):
    if not rel_path:
        return
    path = os.path.join(UPLOAD_DIR, rel_path.lstrip("/").replace("uploads/", "", 1))
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception:
            pass


def delete_comment_with_cascade(db, comment):
    """删留言(含语音文件)+ 清理该留言的未读通知"""
    if comment is None:
        return
    if comment.voice_url:
        _remove_file(comment.voice_url)
    cid = comment.id
    db.delete(comment)
    db.commit()
    cleanup_comment_notifications(db, cid)


def delete_image_with_cascade(db, photo, deleter=None):
    """删照片:级联删留言 → 清通知(含已读) → 删文件 → 写删除通知"""
    if photo is None:
        return
    elder = photo.elderly
    image_id = photo.id
    # ① 级联删除该照片下全部留言(语音文件一并清理)
    comments = db.query(Comment).filter(
        Comment.target_type.in_(("image", "photo")),
        Comment.target_id == image_id,
    ).all()
    for c in comments:
        if c.voice_url:
            _remove_file(c.voice_url)
        db.delete(c)
    db.commit()
    # ② 清除所有引用该照片的通知(含已读,照片已不存在 → 通知即死链)
    cleanup_image_notifications(db, image_id)
    # ③ 文件落盘清理
    _remove_file(photo.original_path)
    if photo.thumbnail_path:
        _remove_file(photo.thumbnail_path)
    db.delete(photo)
    db.commit()
    # ④ 按通知矩阵写 system 删除通知(metadata 不带 imageId)
    notify_image_deleted(db, deleter, elder)
