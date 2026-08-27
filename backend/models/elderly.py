"""老人信息表模型"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base
from .elderly_child import elderly_child


class Elderly(Base):
    __tablename__ = "elderly"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(50), nullable=False)
    age = Column(Integer, nullable=True)
    gender = Column(String(10), nullable=True)
    contact_info = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    health_status = Column(Text, nullable=True)
    preferences = Column(Text, nullable=True)
    guardian_contact = Column(String(100), nullable=True)
    avatar = Column(String(500), nullable=True)
    # 小程序适配:照护志愿者分配(交接说明 §五 elders.volunteer_id;旧数据用 created_by 兜底)
    volunteer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # 两个 FK 都指向 users,必须显式指定 foreign_keys 避免歧义
    creator = relationship("User", foreign_keys=[created_by], back_populates="elderly_records")
    volunteer = relationship("User", foreign_keys=[volunteer_id])
    photos = relationship("Photo", back_populates="elderly")
    activities = relationship("Activity", back_populates="elderly")
    children = relationship("User", secondary=elderly_child, backref="parent_elders")

    def __repr__(self):
        return f"<Elderly(id={self.id}, name={self.name})>"
