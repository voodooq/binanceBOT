import enum
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Numeric, Enum, JSON
from sqlalchemy.orm import relationship

from src.models.base import Base

class StrategyType(str, enum.Enum):
    GRID = "grid"
    HEDGE = "hedge"
    NEUTRAL = "neutral"

class BotStatus(str, enum.Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"

class BotConfig(Base):
    __tablename__ = "bot_configs"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    api_key_id = Column(Integer, ForeignKey("api_keys.id", ondelete="RESTRICT"), nullable=False)
    
    name = Column(String(100), nullable=False)
    symbol = Column(String(20), index=True, nullable=False)
    strategy_type = Column(Enum(StrategyType, name="strategy_type_enum"), nullable=False)
    status = Column(Enum(BotStatus, name="bot_status_enum"), default=BotStatus.IDLE, nullable=False)
    
    # 策略的具体参数 (如 网格上限、下限、网格数 等)，以 JSON 完整存储，便于未来策略拓展
    parameters = Column(JSON, nullable=False) 
    
    # 资产和资金总览
    base_asset = Column(String(20), nullable=False)
    quote_asset = Column(String(20), nullable=False)
    total_investment = Column(Numeric(20, 8), nullable=False, default=0.0)
    
    # 盈利统计 (可选做冗余缓存)
    total_pnl = Column(Numeric(20, 8), nullable=False, default=0.0)
    is_testnet = Column(Boolean, default=False, nullable=False)

    user = relationship("User")
    api_key = relationship("ApiKey")
    trades = relationship("Trade", back_populates="bot_config", cascade="all, delete-orphan")
