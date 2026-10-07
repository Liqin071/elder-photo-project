"""AI 修图 API — POST /ai/enhance(契约 API 文档 §8.1,2026-09-12;2026-09-21 扩展 beautify)

职责:接收原图 → 调 AI 修图服务 → 结果落自有存储 → 返回**可直接下载**的完整直链。
前端拿到 url 后 wx.downloadFile 下载,再作为普通文件走 POST /upload(aiMode 落库)。

硬约束(不合规前端会出问题):
1. data.url 必须无鉴权可直接 GET 200(前端 wx.downloadFile 与冒烟 fetch 都不带 token)
2. 一切失败必须以**业务信封**表达(HTTP 200 + code≠0 + 中文 message),严禁 5xx/非 JSON
3. 同步返回,整体 ≤60s(前端 timeout 120s)
4. mode 白名单:restore 老照片修复 / beautify 照片美化 / enhance 画质增强 / colorize 黑白上色

供应商策略:由环境变量 AI_PROVIDER 决定,前端零感知(只依赖本端点契约)。
- baidu:百度智能云「图像增强与特效」(需 BAIDU_API_KEY + BAIDU_SECRET_KEY)
- local:用 Pillow 做本地增强处理 —— 无需任何密钥即可跑通全链路与验收
- ark:火山方舟 豆包 SeedEdit 图片编辑(需 ARK_API_KEY,可选 ARK_MODEL/ARK_ENDPOINT)
- volcengine:火山引擎视觉智能专项能力(需 VOLC_AK/VOLC_SK,按 Action 对接)
未配置密钥时返回业务失败(前端自动降级原图上传,不阻断主流程)。
"""
import os
import io
import json
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, UploadFile, File, Form, Request
from sqlalchemy.orm import Session
from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

from utils.permissions import get_db, get_current_user, require_user, deny
from utils.exceptions import AppException, ERR_FILE_TYPE, ERR_FILE_TOO_LARGE, ERR_NOT_FOUND, ERR_UPLOAD_FAILED
from utils.timefmt import now_local
from utils.content_security import check_image_hook

router = APIRouter(prefix="/api", tags=["AI 修图"])

AI_MODES = ("restore", "beautify", "enhance", "colorize")
MAX_SIZE = 20 * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp", "application/octet-stream"}
ALLOWED_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

AI_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "ai")
os.makedirs(AI_DIR, exist_ok=True)

# 简单限流(单进程内存计数;AI_DAILY_LIMIT=0 关闭)
_usage = {}
DAILY_LIMIT = int(os.getenv("AI_DAILY_LIMIT", "20"))

# AI 生成内容标识开关(项目方决定:**默认开启**,2026-09 起写入隐式标识)
# - 写入方式:结果图 EXIF ImageDescription(隐式标识,肉眼不可见,不影响观感)+ 处理日志留存
# - 与前端"✨ AI 修复/美化"徽标相互独立:那是产品功能提示,这是合规留痕
# - 如需关闭:环境变量 AI_CONTENT_MARK=0
CONTENT_MARK = os.getenv("AI_CONTENT_MARK", "1").lower() in ("1", "on", "true", "yes")


def _mark_ai_content(jpeg_bytes: bytes, mode: str, provider: str) -> bytes:
    """写入 AI 生成内容隐式标识(仅 AI_CONTENT_MARK=1 时调用)"""
    try:
        img = Image.open(io.BytesIO(jpeg_bytes))
        exif = img.getexif()
        exif[0x010E] = f"AI-generated content (mode={mode}, provider={provider})"  # ImageDescription
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92, exif=exif)
        return buf.getvalue()
    except Exception:
        return jpeg_bytes


def _check_quota(user_id):
    if DAILY_LIMIT <= 0:
        return
    key = (date.today().isoformat(), user_id)
    used = _usage.get(key, 0)
    if used >= DAILY_LIMIT:
        raise AppException(ERR_UPLOAD_FAILED, "今日 AI 修图次数已达上限")
    _usage[key] = used + 1


# ---------------- 本地保底处理(Pillow) ----------------
def _process_local(contents: bytes, mode: str) -> bytes:
    img = Image.open(io.BytesIO(contents))
    img = ImageOps.exif_transpose(img)
    has_alpha = img.mode in ("RGBA", "LA", "P")
    img = img.convert("RGB")

    if mode == "restore":
        # 老照片修复(本地近似):去噪 → 自动对比度 → 轻度锐化,尽量还原而非美化
        out = img.filter(ImageFilter.MedianFilter(size=3))
        out = ImageOps.autocontrast(out, cutoff=1)
        out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=120, threshold=4))
        out = ImageEnhance.Color(out).enhance(0.96)
    elif mode == "beautify":
        # 照片美化:曝光/白平衡/色彩 + 轻度柔化提亮
        out = ImageOps.autocontrast(img, cutoff=1)
        out = ImageEnhance.Brightness(out).enhance(1.05)
        out = ImageEnhance.Contrast(out).enhance(1.08)
        out = ImageEnhance.Color(out).enhance(1.18)
        out = ImageEnhance.Sharpness(out).enhance(1.15)
    elif mode == "enhance":
        # 画质增强:锐化 + 细节增强(不改变内容与色调)
        out = ImageOps.autocontrast(img, cutoff=1)
        out = out.filter(ImageFilter.UnsharpMask(radius=1.6, percent=160, threshold=3))
        out = ImageEnhance.Sharpness(out).enhance(1.5)
    else:  # colorize
        # 黑白上色(本地近似):对灰度图做暖调映射,彩色图做轻度色调统一
        gray = ImageOps.grayscale(img)
        out = ImageOps.colorize(gray, black=(38, 30, 24), white=(255, 246, 232), mid=(150, 120, 96))
        out = ImageEnhance.Color(out).enhance(0.9)

    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


# ---------------- 百度智能云「图像增强与特效」(AI_PROVIDER=baidu) ----------------
# 密钥:BAIDU_API_KEY + BAIDU_SECRET_KEY(控制台 → 应用列表 → API Key / Secret Key)
# 鉴权:先用 API Key + Secret Key 换 access_token(有效期 30 天,内存缓存,失效自动重取)
#
# 能力映射(2026-09 按产品语义重定义;**支持逗号串联多能力组合处理,按顺序依次调用**):
#   老照片修复 restore : 图像清晰度增强(修复模糊/恢复细节) → 黑白上色(仅黑白照自动触发)
#                        → 图像色彩增强 → 图像对比度增强
#   照片美化 beautify  : 图像色彩增强 → 图像对比度增强
#   画质增强 enhance   : 图像清晰度增强
#   黑白上色 colorize  : 黑白图像上色
# 可用环境变量覆盖(BAIDU_EP_<MODE>),见 部署说明.md。
# 特殊标记 `colourize:auto` = 仅当图片接近黑白时才执行上色(避免把彩色照片改色)。
BAIDU_DEFAULT_EP = {
    "restore": "image_quality_enhance,colourize:auto,color_enhance,contrast_enhance",
    "beautify": "color_enhance,contrast_enhance",
    "enhance": "image_quality_enhance",
    "colorize": "colourize",
}
# 灰度判定阈值(HSV 饱和度均值低于该值视为黑白照片 → 触发自动上色);可用 BAIDU_GRAY_THRESHOLD 覆盖
GRAY_THRESHOLD = int(os.getenv("BAIDU_GRAY_THRESHOLD", "28"))
_baidu_token = {"token": None, "expire": 0}
# 百度错误码 → 用户可读提示
BAIDU_ERR_MSG = {
    "4": "AI 修图服务繁忙,请稍后重试",
    "6": "AI 修图服务未开通相应能力,请联系管理员",
    "17": "今日 AI 修图额度已用完,请明天再试",
    "18": "AI 修图请求过于频繁,请稍后重试",
    "19": "AI 修图请求过于频繁,请稍后重试",
    "216630": "图片格式或尺寸不符合要求",
    "216631": "图片过大,请压缩后重试",
    "282810": "图片内容不合规,请更换照片",
}


def _baidu_access_token():
    import time
    import httpx

    now = time.time()
    if _baidu_token["token"] and _baidu_token["expire"] > now:
        return _baidu_token["token"]
    api_key = os.getenv("BAIDU_API_KEY", "")
    secret_key = os.getenv("BAIDU_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图服务未配置")
    with httpx.Client(timeout=15) as client:
        resp = client.post(
            "https://aip.baidubce.com/oauth/2.0/token",
            params={"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key},
        )
    data = resp.json()
    if not data.get("access_token"):
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    _baidu_token["token"] = data["access_token"]
    _baidu_token["expire"] = now + int(data.get("expires_in", 2592000)) - 600
    return _baidu_token["token"]


def _baidu_prepare(contents: bytes) -> str:
    """按百度要求预处理:输出等比缩放后的 JPEG(最长边≤4096、最短边≥50)再 base64"""
    import base64

    img = Image.open(io.BytesIO(contents))
    img = ImageOps.exif_transpose(img).convert("RGB")
    w, h = img.size
    if min(w, h) < 50:
        raise AppException(ERR_UPLOAD_FAILED, "图片太小,请更换更清晰的照片")
    longest = max(w, h)
    if longest > 4096:
        ratio = 4096.0 / longest
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()


def _baidu_call(endpoint: str, token: str, image_b64: str) -> bytes:
    """调用单个百度能力接口,返回结果图片字节"""
    import base64
    import httpx

    url = f"https://aip.baidubce.com/rest/2.0/image-process/v1/{endpoint}?access_token={token}"
    try:
        with httpx.Client(timeout=55) as client:
            resp = client.post(
                url,
                data={"image": image_b64},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        data = resp.json()
    except Exception:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    if "image" in data:
        return base64.b64decode(data["image"])
    code = str(data.get("error_code", ""))
    if code in ("110", "111"):  # token 失效 → 清缓存,由上层重试一次
        _baidu_token["token"] = None
        _baidu_token["expire"] = 0
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    raise AppException(ERR_UPLOAD_FAILED, BAIDU_ERR_MSG.get(code, "AI 修图失败,请稍后重试"))


def _is_grayscale(img) -> bool:
    """判断是否接近黑白照片(HSV 饱和度均值低于阈值)"""
    try:
        hsv = img.convert("HSV")
        if isinstance(hsv, list):
            hsv = hsv[0]
        # 小图采样,避免大图逐个像素统计太慢
        small = hsv.resize((120, 120)) if hasattr(hsv, "resize") else hsv
        sat = ImageStat.Stat(small).mean[1]
        return sat < GRAY_THRESHOLD
    except Exception:
        return False


def _process_baidu(contents: bytes, mode: str) -> bytes:
    """
    百度智能云图像增强与特效:按 BAIDU_EP_<MODE> 顺序**串联多个能力**依次处理。
    - `colourize:auto` 表示"仅当图片接近黑白时才上色"(避免把彩色照片改色)
    - 单步失败不整单失败:跳过该步继续后续步骤;全部失败才抛业务错误
    """
    import base64
    import logging

    ep_env = f"BAIDU_EP_{mode.upper()}"
    chain = os.getenv(ep_env) or BAIDU_DEFAULT_EP.get(mode, "image_quality_enhance")
    steps = [e.strip() for e in chain.split(",") if e.strip()]

    image_bytes = _normalize_jpeg(contents)
    gray_cache = None
    ok_steps, last_error = 0, None

    for step in steps:
        ep = step
        if step.endswith(":auto"):
            ep = step.split(":", 1)[0]
            if gray_cache is None:
                gray_cache = _is_grayscale(Image.open(io.BytesIO(image_bytes)))
            if not gray_cache:
                logging.info("[ai] 跳过 %s(图片非黑白,无需上色)", ep)
                continue
        b64 = base64.b64encode(image_bytes).decode()
        out = None
        for attempt in (1, 2):
            try:
                out = _baidu_call(ep, _baidu_access_token(), b64)
                break
            except AppException as exc:
                _baidu_token_failed = _baidu_token["token"] is None
                if attempt == 1 and _baidu_token_failed:
                    continue  # token 失效已清缓存 → 重取再试一次
                last_error = exc
                logging.warning("[ai] 步骤 %s 失败,跳过: %s", ep, getattr(exc, "detail", exc))
                break
        if out:
            image_bytes = _normalize_jpeg(out)
            ok_steps += 1

    if ok_steps == 0:
        if last_error:
            raise last_error
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    return image_bytes


# ---------------- 远程供应商(占位实现:配了密钥即可用) ----------------
def _process_ark(contents: bytes, mode: str) -> bytes:
    """火山方舟 豆包 SeedEdit 图片编辑(一个接口通吃四 mode,prompt 区分)"""
    import base64
    import httpx

    api_key = os.getenv("ARK_API_KEY", "")
    if not api_key:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图服务未配置")
    endpoint = os.getenv("ARK_ENDPOINT", "https://ark.cn-beijing.volces.com/api/v3/images/generations")
    model = os.getenv("ARK_MODEL", "doubao-seededit-3-0-i2i")
    prompts = {
        "restore": "修复这张老照片:去除划痕、折痕、污渍,修补破损区域,修复模糊与褪色,重点增强人脸细节;"
                   "保持人物身份、姿态、构图与背景完全不变,仅做还原性修复,不添加任何新元素",
        "beautify": "优化这张照片的整体观感:自动校正曝光与白平衡,提升色彩饱和度与通透感,若有人像则做轻度自然美颜;"
                    "保持人物身份与场景内容不变,效果自然不夸张",
        "enhance": "提升这张照片的清晰度与画质:超分辨率重建,恢复细节纹理,降噪并锐化;不改变画面内容、构图与色调",
        "colorize": "给这张黑白照片上色:根据内容推理自然合理的色彩(肤色/衣物/天空/植物等),色调真实不艳俗;"
                    "保持原照片的构图、内容与细节完全不变",
    }
    payload = {
        "model": model,
        "prompt": prompts.get(mode, prompts["restore"]),
        "image": base64.b64encode(contents).decode(),
        "response_format": "url",
        "size": "adaptive",
    }
    with httpx.Client(timeout=55) as client:
        resp = client.post(endpoint, headers={"Authorization": f"Bearer {api_key}"}, json=payload)
    if resp.status_code >= 400:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    data = resp.json()
    items = data.get("data") or []
    url = items[0].get("url") if items else None
    if not url:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    with httpx.Client(timeout=55) as client:
        img_resp = client.get(url)
    if img_resp.status_code != 200:
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")
    return _normalize_jpeg(img_resp.content)


def _process_volcengine(contents: bytes, mode: str) -> bytes:
    """火山引擎视觉智能专项能力(老照片修复/超分/上色)—— 按官方 Action 对接"""
    if not (os.getenv("VOLC_AK") and os.getenv("VOLC_SK")):
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图服务未配置")
    # 接入位置:按官方文档实现 V4 签名 + 各 mode 对应 Action,复用 _normalize_jpeg 归一化输出
    raise AppException(ERR_UPLOAD_FAILED, "AI 修图服务未配置")


def _normalize_jpeg(contents: bytes) -> bytes:
    img = Image.open(io.BytesIO(contents))
    img = ImageOps.exif_transpose(img).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _process(contents: bytes, mode: str) -> bytes:
    provider = os.getenv("AI_PROVIDER", "local").lower()
    if provider == "baidu":
        return _process_baidu(contents, mode)
    if provider == "ark":
        return _process_ark(contents, mode)
    if provider == "volcengine":
        return _process_volcengine(contents, mode)
    return _process_local(contents, mode)


def _looks_like_image(contents: bytes) -> bool:
    """魔数判断(不依赖 PIL 解码):png/jpeg/gif/webp/bmp"""
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if contents.startswith(b"\xff\xd8\xff"):
        return True
    if contents.startswith((b"GIF87a", b"GIF89a")):
        return True
    if contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return True
    if contents.startswith(b"BM"):
        return True
    return False


@router.post("/ai/enhance")
async def ai_enhance(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Form("restore"),
    user=Depends(require_user),
    db: Session = Depends(get_db)
):
    # 鉴权先于文件/参数校验(未登录一律 401,冒烟断言依赖此语义)
    if user.role == "admin":
        deny()  # 与上传权限对齐:管理端无 AI 修图 UI
    mode = (mode or "restore").strip().lower()
    if mode not in AI_MODES:
        raise AppException(ERR_NOT_FOUND, "不支持的修图模式")  # 非法 mode:不落任何文件
    ext = (file.filename or "").rsplit(".", 1)[-1].lower() if "." in (file.filename or "") else ""
    if (file.content_type or "").lower() not in ALLOWED_TYPES and ext not in ALLOWED_EXTS:
        raise AppException(ERR_FILE_TYPE, "文件类型不支持")
    contents = await file.read()
    if not contents:
        raise AppException(ERR_NOT_FOUND, "请上传要处理的图片")
    if len(contents) > MAX_SIZE:
        raise AppException(ERR_FILE_TOO_LARGE, "超过20MB")
    if not _looks_like_image(contents):
        raise AppException(ERR_FILE_TYPE, "文件类型不支持")

    _check_quota(user.id)

    try:
        result = _process(contents, mode)
    except AppException:
        raise
    except Exception:
        # 图片损坏/供应商超时/5xx/限流/内容拒绝 → 业务信封(严禁 5xx 透传,前端降级文案依赖它)
        raise AppException(ERR_UPLOAD_FAILED, "AI 修图失败,请稍后重试")

    provider = os.getenv("AI_PROVIDER", "local").lower()
    if CONTENT_MARK:
        result = _mark_ai_content(result, mode, provider)
        # 处理日志留存(合规备查):供应商/mode/用户/时间
        try:
            log_path = os.path.join(AI_DIR, "enhance.log")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{now_local()} provider={provider} mode={mode} user={user.id}\n")
        except Exception:
            pass

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(AI_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(result)
    base = str(request.base_url).rstrip("/")
    url = base + f"/uploads/ai/{filename}"
    # UGC 图片审核钩子(AI 结果图同样需要;CONTENT_SECURITY_IMAGE=on 时启用,当前占位不阻断)
    check_image_hook(url, openid=user.openid)
    return {"url": url, "mode": mode}
