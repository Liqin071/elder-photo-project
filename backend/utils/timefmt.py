"""
时间工具 — 小程序契约硬约束(交接说明 §四.2):
所有时间字段一律 "YYYY-MM-DD HH:mm" 字符串,禁止 ISO 8601 / 时间戳 / 带时区;
latestImageDate / lastUploadAt 等为刻意的 "YYYY-MM-DD" 纯日期。
统一使用北京时间(Asia/Shanghai)生成与格式化,避免 UTC 差 8 小时。
"""
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    _BEIJING_TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # 旧版 Python 兜底:直接用服务器本地时间
    _BEIJING_TZ = None


def now_local():
    """当前北京时间(naive datetime,可直接落库/序列化)"""
    if _BEIJING_TZ is not None:
        return datetime.now(_BEIJING_TZ).replace(tzinfo=None)
    return datetime.now()


def _to_naive(dt):
    if dt.tzinfo is not None and _BEIJING_TZ is not None:
        return dt.astimezone(_BEIJING_TZ).replace(tzinfo=None)
    return dt


def fmt_dt(dt):
    """datetime → "YYYY-MM-DD HH:mm"(naive / aware 均可;None → None)"""
    if dt is None:
        return None
    return _to_naive(dt).strftime("%Y-%m-%d %H:%M")


def fmt_date(dt):
    """datetime/date → "YYYY-MM-DD" 纯日期(None → None)"""
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return _to_naive(dt).strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")
