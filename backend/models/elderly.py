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
    created_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    creator = relationship("User", back_populates="elderly_records")
    photos = relationship("Photo", back_populates="elderly")
    activities = relationship("Activity", back_populates="elderly")
    children = relationship("User", secondary=elderly_child, backref="parent_elders")

    def __repr__(self):
        return f"<Elderly(id={self.id}, name={self.name})>"
