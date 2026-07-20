"""活动记录表模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base


class Activity(Base):
    __tablename__ = "activities"
    id = Column(Integer, primary_key=True, autoincrement=True)
    elderly_id = Column(Integer, ForeignKey("elderly.id"), nullable=False)
    volunteer_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    activity_date = Column(DateTime, nullable=False)
    photo_count = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    elderly = relationship("Elderly", back_populates="activities")
    volunteer = relationship("User", back_populates="activities")

    def __repr__(self):
        return f"<Activity(id={self.id}, elderly_id={self.elderly_id})>"
