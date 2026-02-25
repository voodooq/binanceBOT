from sqlalchemy import Column, String, Boolean
from sqlalchemy.orm import relationship
from src.models.base import Base

class User(Base):
    __tablename__ = "users"

    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    encrypted_dek = Column(String(255), nullable=True) # User's DEK, encrypted by Master Key
    totp_secret = Column(String(255), nullable=True)   # 2FA Secret, encrypted by DEK
    is_admin = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    notification_settings = relationship("NotificationSetting", back_populates="user", uselist=False, cascade="all, delete-orphan")
