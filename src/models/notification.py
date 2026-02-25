from datetime import datetime
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Enum, JSON
from sqlalchemy.orm import relationship
import enum

from src.models.base import Base

class NotificationLevel(str, enum.Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class Notification(Base):
    """
    持久化通知流水表。
    记录系统向用户发送的所有关键信息。
    """
    __tablename__ = "notifications"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    level = Column(Enum(NotificationLevel, name="notification_level_enum"), default=NotificationLevel.INFO)
    title = Column(String(200), nullable=False)
    message = Column(String(2000), nullable=False)
    is_read = Column(Boolean, default=False)
    data = Column(JSON, nullable=True) # 附加元数据 (如 bot_id, trade_id)
    
    user = relationship("User", back_populates="notifications")

class NotificationSetting(Base):
    """
    用户通知偏好设置。
    控制不同通道的开启状态与敏感度。
    """
    __tablename__ = "notification_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    
    # 渠道开关
    telegram_enabled = Column(Boolean, default=False)
    email_enabled = Column(Boolean, default=False)
    web_enabled = Column(Boolean, default=True) # 默认开启 Web 推送
    
    # 敏感度/最低等级限制
    min_level = Column(Enum(NotificationLevel, name="notification_level_enum"), default=NotificationLevel.INFO)
    
    # 私有凭据
    telegram_chat_id = Column(String(100), nullable=True)
    email_address = Column(String(200), nullable=True)

    user = relationship("User", back_populates="notification_settings")
