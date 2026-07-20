"""主应用"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
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
    if response.status_code == 200 and "application/json" in response.headers.get("content-type", ""):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        try:
            data = json.loads(body.decode())
            return JSONResponse(content={"code": 0, "message": "success", "data": data})
        except:
            return response
    return response

@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    error_map = {
        400: 1003,
        401: 1004,
        403: 1005,
        404: 2001,
        409: 1010
    }
    code = error_map.get(exc.status_code, 5000)
    return JSONResponse(content={"code": code, "message": exc.detail, "data": None})

from api.auth import router as auth_router
app.include_router(auth_router)
from api.elders import router as elders_router
app.include_router(elders_router)
from api.photos import router as photos_router
app.include_router(photos_router)
from api.volunteer import router as volunteer_router
app.include_router(volunteer_router)
from api.timeline import router as timeline_router
app.include_router(timeline_router)

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")

@app.get("/")
def root():
    return {"message": "老年拍照助手API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
