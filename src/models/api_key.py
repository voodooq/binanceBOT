from sqlalchemy import Column, String, Boolean, Integer, ForeignKey
from sqlalchemy.orm import relationship
from src.models.base import Base

class ApiKey(Base):
    __tablename__ = "api_keys"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_key = Column(String(100), index=True, nullable=False)
    encrypted_secret = Column(String(255), nullable=False) # API Secret, encrypted by User's DEK
    is_testnet = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    label = Column(String(50), nullable=True)
    
    user = relationship("User", back_populates="api_keys")
