"""媒体内容安全异步检测任务表(微信 mediaCheckAsync 的 trace_id ↔ 内容 映射)

流程:上传/发语音时提交检测 → 微信异步回调结果 → 按 trace_id 找到目标内容 → 落审核状态
"""
from sqlalchemy import Column, Integer, String, Text, DateTime, func
from .database import Base


class MediaCheckTask(Base):
    __tablename__ = "media_check_tasks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), unique=True, nullable=False, index=True)  # 微信返回的检测任务 id
    target_type = Column(String(20), nullable=False)                        # image / comment
    target_id = Column(Integer, nullable=False)
    media_type = Column(Integer, default=2)                                 # 1=音频 2=图片
    user_id = Column(Integer, nullable=True)                                # 提交人
    status = Column(String(20), default="pending")                          # pending / pass / risky / error
    suggest = Column(String(20), nullable=True)                             # pass / review / risky
    label = Column(Integer, nullable=True)                                  # 违规标签
    raw_result = Column(Text, nullable=True)                                # 原始回调体(备查)
    created_at = Column(DateTime, server_default=func.now())
    checked_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f"<MediaCheckTask(trace_id={self.trace_id}, status={self.status})>"
