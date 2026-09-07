"""老人注册申请表模型(2026-08-28 登录注册重构:N1/N3/N4)

申请落此表(status=pending),管理员通过时才建档即开户(生成 elders + users 行)。
拒绝仅标记,不产生任何账号;微信用户提交时记 wx_user_id,通过时 role 切 elder。
"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base


class ElderApplication(Base):
    __tablename__ = "elder_applications"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)          # 姓名 = 通过后的登录名
    age = Column(Integer, nullable=True)
    gender = Column(String(10), nullable=True)
    phone = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=False)  # 通过后作为老人登录初始密码
    status = Column(String(20), default="pending")       # pending / approved / rejected
    wx_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # 提交申请的微信用户
    elder_id = Column(Integer, ForeignKey("elderly.id"), nullable=True)  # approve 后回填(幂等用)
    created_at = Column(DateTime, server_default=func.now())
    reviewed_at = Column(DateTime, nullable=True)

    wx_user = relationship("User", foreign_keys=[wx_user_id])
    elder = relationship("Elderly", foreign_keys=[elder_id])

    def __repr__(self):
        return f"<ElderApplication(id={self.id}, name={self.name}, status={self.status})>"
