"""评论表模型"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, autoincrement=True)
    target_type = Column(String(20), nullable=False)
    target_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=True)
    content_type = Column(String(10), default="text")
    voice_url = Column(String(500), nullable=True)
    voice_duration = Column(Integer, nullable=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    author = relationship("User")

    def __repr__(self):
        return f"<Comment(id={self.id}, author_id={self.author_id})>"
