"""老人-子女关联表"""
from sqlalchemy import Column, Integer, ForeignKey, Table
from .database import Base

elderly_child = Table(
    "elderly_children",
    Base.metadata,
    Column("elderly_id", Integer, ForeignKey("elderly.id"), primary_key=True),
    Column("child_id", Integer, ForeignKey("users.id"), primary_key=True),
)
