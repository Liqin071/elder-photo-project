"""
权限矩阵辅助 — 交接说明 §六(后端必须强制,前端校验只是体验):
- get_current_user:从 Bearer token 解出 User 对象(失败抛 401)
- elder_of_user:elder 角色定位自己的老人档案(created_by → name → phone 兜底链)
- find_elder_user:老人档案 → 其登录账号(建档即开户/认领/自助注册的 users 行)
- add_binding:写 elderly_children 绑定(带 relationship + created_at)
- check_elder_access:校验用户与老人档案的关系(本人/绑定家属/分配志愿者/admin),失败抛 2003
- get_elder_relationship:绑定关系显示名,无则 "家人"
"""
import json
from fastapi import Header
from sqlalchemy.orm import Session

from models.database import SessionLocal
from models.user import User
from models.elderly import Elderly
from models.elderly_child import elderly_child
from models.notification import Notification
from utils.auth import verify_token
from utils.exceptions import AppException, ERR_AUTH_REQUIRED, ERR_NO_PERMISSION
from utils.timefmt import now_local


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(authorization: str, db: Session):
    """从 Bearer token 解出 User;缺失/无效/不存在/已禁用 → HTTP 401(前端清登录态跳登录页)"""
    if not authorization or not authorization.startswith("Bearer "):
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    uid = verify_token(authorization.split(" ")[1])
    if not uid:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    user = db.query(User).filter(User.id == uid).first()
    if not user:
        raise AppException(ERR_AUTH_REQUIRED, "未登录或token已过期", 401)
    if user.is_active is False:
        raise AppException(ERR_AUTH_REQUIRED, "账户已被禁用", 401)
    return user


def is_admin(user):
    return user.role == "admin"


def deny():
    """统一的无权限抛错(code 2003,HTTP 403)"""
    raise AppException(ERR_NO_PERMISSION, "无权限操作", 403)


def elder_of_user(db: Session, user: User):
    """
    elder 角色 → 自己的老人档案。定位链:
    1. 自己创建的(register-elder 自助注册场景,created_by = 本人)
    2. 姓名匹配(管理员/志愿者代建档场景)
    3. 用户名匹配(管理员建档时 name 为空、username 即老人姓名的场景)
    4. 手机号匹配(兜底)
    非 elder 角色返回 None。
    """
    if user.role != "elder":
        return None
    e = db.query(Elderly).filter(Elderly.created_by == user.id).first()
    if e:
        return e
    if user.name:
        e = db.query(Elderly).filter(Elderly.name == user.name).first()
        if e:
            return e
    if user.username:
        e = db.query(Elderly).filter(Elderly.name == user.username).first()
        if e:
            return e
    if user.phone:
        e = db.query(Elderly).filter(Elderly.contact_info == user.phone).first()
    return e


def check_elder_access(db: Session, user: User, elder_id: int):
    """
    校验 token 用户与 elder_id 的关系;不通过 → 抛 2003。
    返回访问级别:admin / self / family / volunteer。
    规则(交接说明 §六):
    - admin:任意
    - elder:仅自己
    - children:仅绑定的老人
    - volunteer:仅分配给自己的老人(volunteer_id 或旧数据 created_by 兜底)
    """
    if is_admin(user):
        return "admin"
    if user.role == "elder":
        e = elder_of_user(db, user)
        if e and e.id == elder_id:
            return "self"
        deny()
    if user.role == "children":
        if any(e.id == elder_id for e in user.parent_elders):
            return "family"
        deny()
    if user.role == "volunteer":
        e = db.query(Elderly).filter(Elderly.id == elder_id).first()
        if e and (e.volunteer_id == user.id or e.created_by == user.id):
            return "volunteer"
        deny()
    deny()


def get_elder_relationship(db: Session, user_id: int, elder_id: int):
    """绑定关系显示名:elderly_children.relationship,无则 '家人'"""
    row = db.execute(
        elderly_child.select().where(
            elderly_child.c.child_id == user_id,
            elderly_child.c.elderly_id == elder_id,
        )
    ).first()
    if row and row.relationship:
        return row.relationship
    return "家人"


def unread_comment_count(db: Session, user_id: int, elder_id: int) -> int:
    """该老人名下、当前家属未读的留言通知数(metadata.elderId 匹配)"""
    rows = db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.type == "comment",
        Notification.is_read == False,
    ).all()
    cnt = 0
    for n in rows:
        try:
            meta = json.loads(n.metadata_info or "{}")
        except Exception:
            meta = {}
        if meta.get("elderId") == elder_id:
            cnt += 1
    return cnt


def find_elder_user(db: Session, elder):
    """
    老人档案 → 其登录账号(建档即开户 / 认领 / 自助注册产生的 role=elder 的 users 行)。
    定位链:id=created_by → username=姓名 → phone=联系电话。找不到返回 None。
    """
    if elder is None:
        return None
    u = db.query(User).filter(User.id == elder.created_by, User.role == "elder").first()
    if u:
        return u
    u = db.query(User).filter(User.username == elder.name, User.role == "elder").first()
    if u:
        return u
    if elder.contact_info:
        u = db.query(User).filter(User.phone == elder.contact_info, User.role == "elder").first()
    return u


def add_binding(db: Session, child_id: int, elder_id: int, relationship=None):
    """写入 elderly_children 绑定(带 relationship + created_at);已存在则跳过。返回是否新增。"""
    row = db.execute(
        elderly_child.select().where(
            elderly_child.c.child_id == child_id,
            elderly_child.c.elderly_id == elder_id,
        )
    ).first()
    if row:
        return False
    db.execute(
        elderly_child.insert().values(
            child_id=child_id,
            elderly_id=elder_id,
            relationship=(relationship or "").strip() or "其他",
            created_at=now_local(),
        )
    )
    db.commit()
    return True
