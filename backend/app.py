"""主应用"""
from fastapi import FastAPI, Request, HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="老年拍照助手API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def unified_response_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/docs", "/openapi", "/redoc")):
        return response
    # 小程序契约(交接说明 §四.1):所有成功响应统一信封 {code, message, data}
    # 2xx 一律包装(含 201 创建类),非 JSON(静态文件/文件流)不处理
    if response.status_code < 300 and "application/json" in response.headers.get("content-type", ""):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            data = json.loads(body.decode())
            return JSONResponse(
                content={"code": 0, "message": "success", "data": data},
                status_code=response.status_code,
                headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
            )
        except:
            return response
    return response

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    """统一信封:注册在 Starlette 基类上,同时覆盖端点抛出的业务异常与未知路由 404"""
    from utils.exceptions import AppException
    if isinstance(exc, AppException):
        code = exc.biz_code
    elif exc.status_code == 404:
        code = 2001  # 未知路由/资源不存在统一 2001
    else:
        code = 5000
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": exc.detail, "data": None}
    )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """参数校验失败(422)统一信封化,避免前端收到裸 detail 显示"请求失败(422)" """
    msgs = []
    for e in exc.errors():
        loc = ".".join(str(x) for x in e.get("loc", []) if x != "body")
        msg = e.get("msg", "参数错误")
        msgs.append(f"{loc} {msg}" if loc else msg)
    return JSONResponse(
        status_code=400,
        content={"code": 1003, "message": msgs[0] if msgs else "参数校验失败", "data": None}
    )

from api.auth import router as auth_router
app.include_router(auth_router)
from api.elders import router as elders_router
app.include_router(elders_router)
from api.photos import router as photos_router
from api.volunteer import router as volunteer_router
app.include_router(photos_router)
app.include_router(volunteer_router)
from api.timeline import router as timeline_router
app.include_router(timeline_router)
from api.comments import router as comments_router
app.include_router(comments_router)
from api.notifications import router as notifications_router
app.include_router(notifications_router)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/")
def root():
    return {"message": "老年拍照助手API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="老年拍照助手API",
        version="1.0.0",
        routes=app.routes,
    )
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
    }
    openapi_schema["security"] = [{"BearerAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi
