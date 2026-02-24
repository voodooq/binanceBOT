from typing import Any, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from src.db.session import get_db
from src.api.dependencies import get_current_user
from src.models.user import User
from src.models.bot import BotConfig, BotStatus

router = APIRouter()

@router.get("/overview")
async def get_dashboard_overview(
    api_key_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    # 投资总额
    inv_query = select(func.sum(BotConfig.total_investment)).where(BotConfig.user_id == current_user.id)
    if api_key_id:
        inv_query = inv_query.where(BotConfig.api_key_id == api_key_id)
    inv_result = await db.execute(inv_query)
    total_investment = inv_result.scalar() or 0

    # 累计收益
    profit_query = select(func.sum(BotConfig.total_pnl)).where(BotConfig.user_id == current_user.id)
    if api_key_id:
        profit_query = profit_query.where(BotConfig.api_key_id == api_key_id)
    profit_result = await db.execute(profit_query)
    total_profit = profit_result.scalar() or 0

    # 活跃机器人
    active_query = select(func.count(BotConfig.id)).where(BotConfig.user_id == current_user.id, BotConfig.status == BotStatus.RUNNING)
    if api_key_id:
        active_query = active_query.where(BotConfig.api_key_id == api_key_id)
    active_result = await db.execute(active_query)
    active_bots = active_result.scalar() or 0

    return {
        "total_investment": float(total_investment),
        "total_profit": float(total_profit),
        "active_bots": int(active_bots),
        "risk_level": "低"
    }
