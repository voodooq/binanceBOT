import enum
from sqlalchemy import Column, Integer, String, ForeignKey, Numeric, Enum, DateTime
from sqlalchemy.orm import relationship

from src.models.base import Base

class OrderSide(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"

class OrderStatus(str, enum.Enum):
    NEW = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"
    EXPIRED = "expired"

class Trade(Base):
    """
    记录每个 Bot 的挂单和成交详情。这些数据用于前端挂单可视化和报表统计。
    """
    __tablename__ = "trades"

    bot_config_id = Column(Integer, ForeignKey("bot_configs.id", ondelete="CASCADE"), nullable=False)
    
    # 交易所的原始订单 ID，有些交易可能是没有成交的挂单
    exchange_order_id = Column(String(100), index=True, nullable=True)
    symbol = Column(String(20), nullable=False)
    
    side = Column(Enum(OrderSide, name="order_side_enum"), nullable=False)
    price = Column(Numeric(20, 8), nullable=False) # 挂单/成交价格
    quantity = Column(Numeric(20, 8), nullable=False) # 挂单/成交数量
    executed_qty = Column(Numeric(20, 8), nullable=False, default=0.0) # 已成交数量
    
    status = Column(Enum(OrderStatus, name="order_status_enum"), nullable=False, default=OrderStatus.NEW)
    fee = Column(Numeric(20, 8), nullable=True, default=0.0)
    fee_asset = Column(String(20), nullable=True)

    bot_config = relationship("BotConfig", back_populates="trades")
