"""业务异常类 — 支持自定义业务错误码"""
from fastapi import HTTPException


class AppException(HTTPException):
    """携带业务错误码的 HTTP 异常"""
    def __init__(self, biz_code: int, detail: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)
        self.biz_code = biz_code


# 认证相关错误码
ERR_AUTH_FAILED = 1001          # 用户名或密码错误
ERR_ACCOUNT_DISABLED = 1002     # 账户已被禁用
ERR_AUTH_REQUIRED = 1004        # 未登录或 token 已过期
ERR_PERMISSION_DENIED = 1005    # 无权限
ERR_USERNAME_EXISTS = 1010      # 用户名已存在
ERR_INVITE_INVALID = 1011       # 邀请码无效
ERR_PASSWORD_SHORT = 1012       # 密码长度不足

# 老人相关错误码
ERR_NOT_FOUND = 2001            # 资源不存在
ERR_HAS_PHOTOS = 2002           # 有影像数据不能删
ERR_NO_PERMISSION = 2003        # 无权限操作

# 上传相关错误码
ERR_FILE_TYPE = 3001            # 文件类型不支持
ERR_FILE_TOO_LARGE = 3002       # 超过 20MB
ERR_UPLOAD_FAILED = 3003        # 上传失败
ERR_ELDER_NOT_FOUND = 3004      # 老人不存在

ERR_SERVER = 5000               # 服务器内部错误
