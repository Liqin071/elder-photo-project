"""主应用"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

app = FastAPI(title="老年拍照助手API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from api.auth import router as auth_router
app.include_router(auth_router)

@app.get("/")
def root():
    return {"message": "老年拍照助手API", "version": "1.0.0"}

@app.get("/health")
def health_check():
    return {"status": "healthy"}
