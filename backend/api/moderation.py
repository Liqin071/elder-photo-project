"""UGC 合规:用户举报 + 管理员处置 + 微信内容安全异步回调

接口(契约外新增,前端接入后即为产品功能):
- POST /reports                    用户举报内容(image/comment)
- GET  /admin/reports              管理员查看举报队列(status/reason 过滤)
- POST /admin/reports/:id/handle   处置:delete=删除违规内容 / reject=驳回举报
- GET  /admin/moderation           管理员查看待审/违规内容(异步检测结果)
- GET/POST /wx/media-check-callback 微信「消息推送」回调:URL 校验 + mediaCheckAsync 结果落库

上线配置(小程序后台):
  开发管理 → 开发设置 → 消息推送 → 服务器地址填:
    https://guangyingliuhen.cn/api/wx/media-check-callback
  Token 填入服务器 .env 的 WX_MSG_TOKEN(用于回调签名校验);数据格式选 JSON
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional

from models.report import ContentReport
from models.media_check import MediaCheckTask
from models.photo import Photo
from models.comment import Comment
from models.user import User
from utils.permissions import get_db, get_current_user, is_admin, deny
from utils.exceptions import AppException, ERR_NOT_FOUND
from utils.content_ops import delete_image_with_cascade, delete_comment_with_cascade
from utils.content_security import verify_wx_signature, apply_media_check_result
from utils.timefmt import fmt_dt

router = APIRouter(prefix="/api", tags=["UGC 合规"])

REPORT_REASONS = ("色情低俗", "违法违规", "虚假欺诈", "侵权抄袭", "骚扰辱骂", "其他")


class ReportCreate(BaseModel):
    targetType: str = Field(..., description="image / comment")
    targetId: int = Field(..., description="目标内容 id")
    reason: str = Field(..., description="举报原因")
    detail: Optional[str] = Field(None, description="补充说明")


class ReportHandle(BaseModel):
    action: str = Field(..., description="delete=删除违规内容 / reject=驳回举报")
    note: Optional[str] = Field(None, description="处置备注")


def _report_to_dict(r, db):
    target = None
    if r.target_type == "image":
        p = db.query(Photo).filter(Photo.id == r.target_id).first()
        if p:
            target = {"exists": True, "elderId": p.elderly_id, "note": p.note,
                      "uploaderName": (p.volunteer.name or p.volunteer.username) if p.volunteer else None}
        else:
            target = {"exists": False}
    elif r.target_type == "comment":
        c = db.query(Comment).filter(Comment.id == r.target_id).first()
        if c:
            target = {"exists": True, "content": (c.content or "")[:80], "contentType": c.content_type,
                      "authorName": (c.author.name or c.author.username) if c.author else None}
        else:
            target = {"exists": False}
    return {
        "id": r.id,
        "targetType": r.target_type,
        "targetId": r.target_id,
        "reason": r.reason,
        "detail": r.detail,
        "status": r.status,
        "reporterId": r.reporter_id,
        "reporterName": (r.reporter.name or r.reporter.username) if r.reporter else None,
        "handlerId": r.handler_id,
        "handleNote": r.handle_note,
        "createdAt": fmt_dt(r.created_at),
        "handledAt": fmt_dt(r.handled_at),
        "target": target,
    }


# ---------------- 用户举报 ----------------
@router.post("/reports", status_code=201)
def create_report(
    req: ReportCreate,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if req.targetType not in ("image", "comment"):
        raise AppException(1003, "举报对象类型不支持")
    if req.targetType == "image":
        target = db.query(Photo).filter(Photo.id == req.targetId).first()
    else:
        target = db.query(Comment).filter(Comment.id == req.targetId).first()
    if not target:
        raise AppException(ERR_NOT_FOUND, "举报的内容不存在或已被删除")
    if req.targetType == "comment" and target.author_id == user.id:
        raise AppException(1003, "不能举报自己的留言")
    if req.targetType == "image" and getattr(target, "volunteer_id", None) == user.id:
        raise AppException(1003, "不能举报自己上传的照片")
    dup = db.query(ContentReport).filter(
        ContentReport.reporter_id == user.id,
        ContentReport.target_type == req.targetType,
        ContentReport.target_id == req.targetId,
        ContentReport.status == "pending",
    ).first()
    if dup:
        raise AppException(1003, "您已举报过该内容,我们正在处理")
    reason = (req.reason or "其他").strip()
    r = ContentReport(
        reporter_id=user.id,
        target_type=req.targetType,
        target_id=req.targetId,
        reason=reason if reason in REPORT_REASONS else "其他",
        detail=(req.detail or "").strip() or None,
        status="pending",
    )
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id}


# ---------------- 管理员:举报队列 ----------------
@router.get("/admin/reports")
def list_reports(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()
    q = db.query(ContentReport).order_by(ContentReport.created_at.desc())
    if status:
        q = q.filter(ContentReport.status == status)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [_report_to_dict(r, db) for r in rows],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size,
    }


@router.post("/admin/reports/{report_id}/handle")
def handle_report(
    report_id: int,
    req: ReportHandle,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """处置举报:delete=删除违规内容(级联)/ reject=驳回"""
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()
    r = db.query(ContentReport).filter(ContentReport.id == report_id).first()
    if not r:
        raise AppException(ERR_NOT_FOUND, "举报记录不存在")
    if r.status != "pending":
        raise AppException(ERR_NOT_FOUND, "该举报已处理")
    action = (req.action or "").strip().lower()
    if action not in ("delete", "reject"):
        raise AppException(1003, "处置动作不支持")
    if action == "delete":
        if r.target_type == "image":
            photo = db.query(Photo).filter(Photo.id == r.target_id).first()
            if photo:
                delete_image_with_cascade(db, photo, user)
        else:
            comment = db.query(Comment).filter(Comment.id == r.target_id).first()
            if comment:
                delete_comment_with_cascade(db, comment)
        r.status = "handled"
    else:
        r.status = "rejected"
    r.handler_id = user.id
    r.handle_note = (req.note or "").strip() or None
    from utils.timefmt import now_local
    r.handled_at = now_local()
    db.commit()
    return None


# ---------------- 管理员:内容审核结果 ----------------
@router.get("/admin/moderation")
def list_moderation(
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    """查看媒体检测任务(默认全部;status=pending/risky/pass 过滤)"""
    user = get_current_user(authorization, db)
    if not is_admin(user):
        deny()
    q = db.query(MediaCheckTask).order_by(MediaCheckTask.created_at.desc())
    if status:
        q = q.filter(MediaCheckTask.status == status)
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "list": [{
            "id": t.id, "traceId": t.trace_id, "targetType": t.target_type, "targetId": t.target_id,
            "mediaType": t.media_type, "status": t.status, "suggest": t.suggest, "label": t.label,
            "createdAt": fmt_dt(t.created_at), "checkedAt": fmt_dt(t.checked_at),
        } for t in rows],
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size,
    }


# ---------------- 微信「消息推送」回调 ----------------
@router.get("/wx/media-check-callback")
def wx_callback_verify(signature: str = "", timestamp: str = "", nonce: str = "", echostr: str = ""):
    """URL 有效性校验(小程序后台配置消息推送地址时会 GET 一次)"""
    if verify_wx_signature(signature, timestamp, nonce):
        return PlainTextResponse(echostr or "success")
    return PlainTextResponse("invalid signature", status_code=403)


@router.post("/wx/media-check-callback")
async def wx_callback_receive(
    request: Request,
    signature: str = "",
    timestamp: str = "",
    nonce: str = "",
    db: Session = Depends(get_db)
):
    """
    接收 mediaCheckAsync 结果推送(JSON 格式)。
    微信要求 5 秒内响应,响应体任意;处理失败也不应抛 5xx(否则微信会重试)。
    """
    if not verify_wx_signature(signature, timestamp, nonce):
        return PlainTextResponse("invalid signature", status_code=403)
    try:
        payload = await request.json()
    except Exception:
        return PlainTextResponse("ok")
    # 事件类型过滤:wxa_media_check(兼容不同字段命名)
    try:
        apply_media_check_result(db, payload if isinstance(payload, dict) else {})
    except Exception:
        pass
    return PlainTextResponse("ok")
