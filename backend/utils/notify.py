"""通知写入辅助(2026-08-28 登录注册重构)"""
import json
from sqlalchemy.orm import Session
from models.notification import Notification
from utils.permissions import find_elder_user


def notify_bind_elder(db: Session, elder, child_name: str):
    """家属绑定成功后给老人账号写一条 type=system 通知(老人端铃铛可见)"""
    target = find_elder_user(db, elder)
    if not target:
        return
    db.add(Notification(
        user_id=target.id,
        type="system",
        title="新家属绑定",
        content=f"家属 {child_name} 已绑定到您的档案",
        metadata_info=json.dumps({"elderId": elder.id}),
    ))
    db.commit()
