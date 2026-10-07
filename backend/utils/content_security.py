"""内容安全(UGC 合规)—— 方案 B:文字走微信 msgSecCheck;图片审核留钩子

设计取舍(与项目方确认):
- 默认**关闭**(CONTENT_SECURITY=off):不阻断现有联调与验收;上线提审前打开。
- 文字(留言):`msgSecCheck` 同步检测,判定违规 → 业务失败(前端 toast message)。
- 图片(照片/头像/AI 结果图):微信侧是**异步**检测(mediaCheckAsync + 结果回调),
  需要额外的回调地址与状态落库,故此处只留**钩子函数**与调用点(CONTENT_SECURITY_IMAGE=on 时打印待实现提示),
  上线前按官方文档补齐即可,不影响当前链路。
- 一切网络异常/未配置密钥 → **降级放行**(绝不因为审核服务挂了导致用户传不了照片)。
"""
import os
import time

import httpx

from utils.exceptions import AppException, ERR_CONTENT_RISKY

# 开关(默认关闭)
TEXT_ENABLED = os.getenv("CONTENT_SECURITY", "off").lower() in ("on", "1", "true", "yes")
IMAGE_ENABLED = os.getenv("CONTENT_SECURITY_IMAGE", "off").lower() in ("on", "1", "true", "yes")

_token_cache = {"token": None, "expire": 0}

# 场景值:2 = 评论(官方文档 scene 枚举)
SCENE_COMMENT = 2


def _access_token():
    """微信 access_token 获取与缓存(提前 5 分钟过期,避免边界失效)"""
    appid = os.getenv("WX_APPID", "")
    secret = os.getenv("WX_SECRET", "")
    if not appid or not secret:
        return None
    now = time.time()
    if _token_cache["token"] and _token_cache["expire"] > now:
        return _token_cache["token"]
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.get(
                "https://api.weixin.qq.com/cgi-bin/token",
                params={"grant_type": "client_credential", "appid": appid, "secret": secret},
            )
        data = resp.json()
        if data.get("access_token"):
            _token_cache["token"] = data["access_token"]
            _token_cache["expire"] = now + int(data.get("expires_in", 7200)) - 300
            return _token_cache["token"]
    except Exception:
        return None
    return None


def check_text(content: str, openid: str = None, scene: int = SCENE_COMMENT) -> str:
    """
    文字内容安全检测。返回值语义(仅供日志):
      'skip'     开关关闭或内容为空
      'pass'     微信判定通过
      'degraded' 未配置密钥/网络异常/接口异常 → 降级放行
    违规时抛业务失败(ERR_CONTENT_RISKY),由前端 toast。
    """
    if not TEXT_ENABLED:
        return "skip"
    text = (content or "").strip()
    if not text:
        return "skip"
    token = _access_token()
    if not token:
        return "degraded"
    try:
        with httpx.Client(timeout=5) as client:
            resp = client.post(
                f"https://api.weixin.qq.com/wxa/msg_sec_check?access_token={token}",
                json={"content": text, "version": 2, "scene": scene, "openid": openid or ""},
            )
        data = resp.json()
    except Exception:
        return "degraded"
    errcode = data.get("errcode")
    if errcode == 87014:  # 内容含有违法违规内容(v1 语义)
        raise AppException(ERR_CONTENT_RISKY, "内容包含违规信息,请修改后重试")
    if errcode not in (0, None):
        # 61010(openid 无效)/40001(token 失效)等 → 降级放行,不让审核服务影响主流程
        return "degraded"
    suggest = ((data.get("result") or {}).get("suggest") or "").lower()
    if suggest in ("risky", "review"):
        raise AppException(ERR_CONTENT_RISKY, "内容包含违规信息,请修改后重试")
    return "pass"


def submit_media_check(db, media_url: str, media_type: int, target_type: str,
                       target_id: int, user_id=None, openid: str = None):
    """
    提交媒体内容异步检测(微信 mediaCheckAsync),并登记 trace_id ↔ 内容 的映射。
    - media_type:1=音频 2=图片;scene:1=资料 2=评论 3=论坛 4=社交日志
    - 结果为**异步回调**(POST 到小程序后台「消息推送」配置的 URL,见 api/moderation.py)
    - 任何失败都**降级放行**(返回 None,不阻断上传),仅记录日志
    """
    if not IMAGE_ENABLED:
        return None
    token = _access_token()
    if not token:
        return None
    try:
        with httpx.Client(timeout=8) as client:
            resp = client.post(
                f"https://api.weixin.qq.com/wxa/media_check_async?access_token={token}",
                json={
                    "media_url": media_url,
                    "media_type": media_type,
                    "version": 2,
                    "scene": SCENE_COMMENT if target_type == "comment" else 4,
                    "openid": openid or "",
                },
            )
        data = resp.json()
    except Exception:
        return None
    trace_id = data.get("trace_id")
    if not trace_id:
        return None
    from models.media_check import MediaCheckTask
    task = MediaCheckTask(
        trace_id=trace_id,
        target_type=target_type,
        target_id=target_id,
        media_type=media_type,
        user_id=user_id,
        status="pending",
    )
    db.add(task)
    db.commit()
    return task


def verify_wx_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """校验微信「消息推送」签名:sha1(sort(token, timestamp, nonce))"""
    import hashlib

    token = os.getenv("WX_MSG_TOKEN", "")
    if not token:
        return True  # 未配置 Token 时不校验(便于联调;上线务必配置)
    if not (signature and timestamp and nonce):
        return False
    raw = "".join(sorted([token, timestamp, nonce]))
    return hashlib.sha1(raw.encode()).hexdigest() == signature


def _suggest_of(payload: dict) -> str:
    """从回调体取总体结论:risky / review / pass"""
    result = payload.get("result") or {}
    suggest = (result.get("suggest") or "").lower()
    if not suggest:
        for item in payload.get("detail") or []:
            s = (item.get("suggest") or "").lower()
            if s in ("risky", "review"):
                return s
            suggest = suggest or s
    if payload.get("isrisky"):
        return "risky"
    return suggest or "pass"


def _label_of(payload: dict) -> int:
    result = payload.get("result") or {}
    if result.get("label") is not None:
        return result.get("label")
    for item in payload.get("detail") or []:
        if item.get("label") is not None:
            return item.get("label")
    return None


def apply_media_check_result(db, payload: dict) -> dict:
    """
    处理微信 mediaCheckAsync 回调:更新任务状态 + 目标内容的审核状态。
    违规(risky)→ 目标内容 moderation_status='risky',列表接口自动隐藏。
    """
    import json
    from models.media_check import MediaCheckTask
    from models.photo import Photo
    from models.comment import Comment
    from utils.timefmt import now_local

    trace_id = payload.get("trace_id")
    if not trace_id:
        return {"ok": False, "reason": "no trace_id"}
    task = db.query(MediaCheckTask).filter(MediaCheckTask.trace_id == trace_id).first()
    if not task:
        return {"ok": False, "reason": "task not found"}
    suggest = _suggest_of(payload)
    label = _label_of(payload)
    task.suggest = suggest
    task.label = label
    task.raw_result = json.dumps(payload, ensure_ascii=False)[:2000]
    task.checked_at = now_local()
    task.status = "risky" if suggest == "risky" else ("pass" if suggest == "pass" else suggest)
    # 同步到目标内容
    target = None
    if task.target_type == "image":
        target = db.query(Photo).filter(Photo.id == task.target_id).first()
    elif task.target_type == "comment":
        target = db.query(Comment).filter(Comment.id == task.target_id).first()
    if target is not None:
        target.moderation_status = "risky" if suggest == "risky" else "pass"
    db.commit()
    return {"ok": True, "status": task.status, "suggest": suggest, "target": f"{task.target_type}:{task.target_id}"}


def check_image_hook(image_url: str, openid: str = None) -> None:
    """兼容旧调用点(同步钩子);异步检测请用 submit_media_check()"""
    return None
