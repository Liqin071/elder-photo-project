"""用户表模型"""
from sqlalchemy import Column, Integer, String, DateTime, Enum, func
from sqlalchemy.orm import relationship
from .database import Base
import enum


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    ELDER = "elder"
    VOLUNTEER = "volunteer"
    CHILDREN = "children"


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    email = Column(String(100), unique=True)
    role = Column(Enum(UserRole), default=UserRole.VOLUNTEER)
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime)
    reset_token = Column(String(500), unique=True, nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    name = Column(String(100), nullable=True)
    avatar = Column(String(500), nullable=True)
    phone = Column(String(20), nullable=True)
    elderly_records = relationship("Elderly", back_populates="creator")
    photos = relationship("Photo", back_populates="volunteer")
    activities = relationship("Activity", back_populates="volunteer")

    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
