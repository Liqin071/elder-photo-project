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
    upload_time = Column(DateTime, server_default=func.now())

    elderly = relationship("Elderly", back_populates="photos")
    volunteer = relationship("User", back_populates="photos")

    def __repr__(self):
        return f"<Photo(id={self.id}, elderly_id={self.elderly_id})>"
