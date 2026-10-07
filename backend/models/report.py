"""用户举报表(UGC 合规:举报入口的后端落地)"""
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from .database import Base


class ContentReport(Base):
    __tablename__ = "content_reports"
    id = Column(Integer, primary_key=True, autoincrement=True)
    reporter_id = Column(Integer, ForeignKey("users.id"), nullable=False)   # 举报人
    target_type = Column(String(20), nullable=False)                        # image / comment
    target_id = Column(Integer, nullable=False)
    reason = Column(String(50), nullable=False)                             # 举报原因(枚举中文)
    detail = Column(Text, nullable=True)                                    # 补充说明
    status = Column(String(20), default="pending")                          # pending / handled / rejected
    handler_id = Column(Integer, ForeignKey("users.id"), nullable=True)      # 处置人(管理员)
    handle_note = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    handled_at = Column(DateTime, nullable=True)

    reporter = relationship("User", foreign_keys=[reporter_id])
    handler = relationship("User", foreign_keys=[handler_id])

    def __repr__(self):
        return f"<ContentReport(id={self.id}, target={self.target_type}:{self.target_id}, status={self.status})>"
