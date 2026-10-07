"""照片表模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base


class Photo(Base):
    __tablename__ = "photos"
    id = Column(Integer, primary_key=True, autoincrement=True)
    elderly_id = Column(Integer, ForeignKey("elderly.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_path = Column(String(500), nullable=False)
    processed_path = Column(String(500), nullable=True)
    thumbnail_path = Column(String(500), nullable=True)
    photo_type = Column(String(20), default="normal")
    status = Column(String(20), default="original")
    ai_enhancement_type = Column(String(30), default="none")
    note = Column(Text, nullable=True)
    # 2026-09-12:AI 修图效果(restore/beautify/enhance/colorize;NULL=原图直传),详情页据此展示徽标
    ai_mode = Column(String(20), nullable=True)
    # UGC 内容安全审核状态:NULL=未审核(审核开关关闭时的常态)/ pending / pass / risky(违规,列表隐藏)
    moderation_status = Column(String(20), nullable=True)
    file_size = Column(Integer, nullable=True)
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    upload_time = Column(DateTime, server_default=func.now())

    elderly = relationship("Elderly", back_populates="photos")
    volunteer = relationship("User", back_populates="photos")

    def __repr__(self):
        return f"<Photo(id={self.id}, elderly_id={self.elderly_id})>"
