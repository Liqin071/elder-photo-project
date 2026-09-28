"""AI 修图 API — POST /ai/enhance(契约 API 文档 §8.1,2026-09-12;2026-09-21 扩展 beautify)

职责:接收原图 → 调 AI 修图服务 → 结果落自有存储 → 返回**可直接下载**的完整直链。
前端拿到 url 后 wx.downloadFile 下载,再作为普通文件走 POST /upload(aiMode 落库)。

硬约束(不合规前端会出问题):
1. data.url 必须无鉴权可直接 GET 200(前端 wx.downloadFile 与冒烟 fetch 都不带 token)
2. 一切失败必须以**业务信封**表达(HTTP 200 + code≠0 + 中文 message),严禁 5xx/非 JSON
3. 同步返回,整体 ≤60s(前端 timeout 120s)
4. mode 白名单:restore 老照片修复 / beautify 照片美化 / enhance 画质增强 / colorize 黑白上色

供应商策略:由环境变量 AI_PROVIDER 决定,前端零感知(只依赖本端点契约)。
- local(默认):用 Pillow 做本地增强处理 —— 无需任何密钥即可跑通全链路与验收;
  效果是"确定性图像增强",非生成式修复,适合联调/演示。
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
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from utils.permissions import get_db, get_current_user, deny
from utils.exceptions import AppException, ERR_FILE_TYPE, ERR_FILE_TOO_LARGE, ERR_NOT_FOUND, ERR_UPLOAD_FAILED

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
    authorization: str = Header(None),
    db: Session = Depends(get_db)
):
    user = get_current_user(authorization, db)
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

    filename = f"{uuid.uuid4().hex}.jpg"
    filepath = os.path.join(AI_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(result)
    base = str(request.base_url).rstrip("/")
    return {"url": base + f"/uploads/ai/{filename}", "mode": mode}
