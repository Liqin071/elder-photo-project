"""老人-子女(家属)关联表"""
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Table, func
from .database import Base

elderly_child = Table(
    "elderly_children",
    Base.metadata,
    Column("elderly_id", Integer, ForeignKey("elderly.id"), primary_key=True),
    Column("child_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("relationship", String(20), nullable=True),  # 显示名("母亲"/"父亲"/"儿子"/...),无则回退"家人"
    Column("created_at", DateTime, server_default=func.now()),  # 绑定时间(N7 families.boundAt)
)
