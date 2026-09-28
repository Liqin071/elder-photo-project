"""
登录失败限流(防暴力破解;单进程内存计数,重启即清零)

为什么需要:登录接口是唯一无需鉴权即可尝试的口令入口,公网暴露时必须限制尝试频率。
- 统计维度:用户名 + 客户端 IP(uvicorn 开启 proxy-headers,经 Nginx 时取真实 IP)
- 触发后锁定一段时间,返回业务失败(HTTP 200 + code≠0 + 中文提示),不泄露账号是否存在
- 可用环境变量调整:LOGIN_MAX_FAILS(默认 10)/LOGIN_WINDOW_SECONDS(默认 300)/LOGIN_LOCK_SECONDS(默认 600)
"""
import os
import time

MAX_FAILS = int(os.getenv("LOGIN_MAX_FAILS", "10"))
WINDOW_SECONDS = int(os.getenv("LOGIN_WINDOW_SECONDS", "300"))
LOCK_SECONDS = int(os.getenv("LOGIN_LOCK_SECONDS", "600"))

# key -> {"count": int, "first": ts, "locked_until": ts}
_state = {}


def _now():
    return time.time()


def check_login_allowed(key: str):
    """返回剩余锁定秒数(0 = 允许尝试)"""
    rec = _state.get(key)
    if not rec:
        return 0
    locked_until = rec.get("locked_until", 0)
    if locked_until > _now():
        return int(locked_until - _now())
    # 窗口过期 → 重置
    if _now() - rec.get("first", 0) > WINDOW_SECONDS:
        _state.pop(key, None)
    return 0


def record_login_failure(key: str):
    rec = _state.get(key)
    now = _now()
    if not rec or now - rec.get("first", 0) > WINDOW_SECONDS:
        rec = {"count": 0, "first": now, "locked_until": 0}
    rec["count"] += 1
    if rec["count"] >= MAX_FAILS:
        rec["locked_until"] = now + LOCK_SECONDS
        rec["count"] = 0
        rec["first"] = now
    _state[key] = rec
    return rec


def clear_login_failures(key: str):
    _state.pop(key, None)


def client_key(username: str, request=None) -> str:
    ip = ""
    try:
        if request is not None and request.client:
            ip = request.client.host or ""
    except Exception:
        ip = ""
    return f"{(username or '').strip().lower()}|{ip}"
