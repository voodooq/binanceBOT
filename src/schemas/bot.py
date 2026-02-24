from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models.bot import BotStatus, StrategyType

class BotConfigBase(BaseModel):
    name: str = Field(..., max_length=100)
    symbol: str = Field(..., max_length=20)
    strategy_type: StrategyType
    parameters: dict[str, Any] = Field(..., description="策略的详细 JSON 参数")
    base_asset: str = Field(..., max_length=20)
    quote_asset: str = Field(..., max_length=20)
    total_investment: Decimal = Field(..., ge=0)
    is_testnet: bool = False
    api_key_id: int = Field(..., description="绑定的 API Key ID")

class BotConfigCreate(BotConfigBase):
    pass

class BotConfigUpdate(BaseModel):
    name: str | None = None
    parameters: dict[str, Any] | None = None
    total_investment: Decimal | None = None

class BotConfigResponse(BotConfigBase):
    id: int
    user_id: int
    status: BotStatus
    total_pnl: Decimal
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
