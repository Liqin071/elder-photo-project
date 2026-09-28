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


def check_image_hook(image_url: str, openid: str = None) -> None:
    """
    图片审核钩子(CONTENT_SECURITY_IMAGE=on 时生效)。
    实现位置:调用微信 mediaCheckAsync(异步)→ 结果回调接口落库 → 违规图片下架/标记。
    当前为占位:不阻断任何流程。
    """
    if not IMAGE_ENABLED:
        return None
    # TODO(上线前):调用 https://api.weixin.qq.com/wxa/media_check_async
    #   并新增回调路由接收 trace_id 结果(wx 会 POST 到配置的 URL),违规时置图片状态为 blocked。
    return None
