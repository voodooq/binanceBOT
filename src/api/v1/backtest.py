from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional, Any

from src.db.session import get_db
from src.api.dependencies import get_current_user
from src.models.user import User
from src.models.bot import BotConfig, StrategyType
from src.engine.backtest_engine import BacktestEngine
from src.engine.strategy_manager import strategy_manager
from src.exchanges.binance_client import BinanceClient, ClientConfig
from src.utils.rate_limiter import RateLimiter

router = APIRouter()

@router.post("/run")
async def run_backtest(
    bot_id: int,
    days: int = 7,
    interval: str = "1h",
    config_override: Optional[dict] = Body(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    运行历史回测。
    支持两种模式：
    1. 已创建的机器人：通过 bot_id 拉取配置
    2. 未创建的机器人 (拟合预检)：bot_id=0, 从 config_override 获取参数
    """
    bot = None
    if bot_id > 0:
        # 模式 1：基于现有 Bot
        bot = await db.get(BotConfig, bot_id)
        if not bot or bot.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="未找到该机器人或无权访问")
    else:
        # 模式 2：未创建 Bot，动态拟合
        if not config_override:
            raise HTTPException(status_code=400, detail="拟合模式必须提供 config_override 参数")
        
        # 模拟一个符合需求的 BotConfig 对象
        bot = BotConfig(
            id=0,
            user_id=current_user.id,
            name=config_override.get("name", "Backtest_Temp"),
            symbol=config_override.get("symbol", "BTCUSDT"),
            strategy_type=config_override.get("strategy_type", "grid"),
            parameters=config_override.get("parameters", {}),
            total_investment=config_override.get("total_investment", 1000),
            is_testnet=True
        )

    # 2. 获取策略实现类
    strategy_class = strategy_manager._strategy_registry.get(bot.strategy_type)
    if not strategy_class:
        raise HTTPException(status_code=400, detail=f"不支持类型 [{bot.strategy_type}] 的回测")

    # 3. 抓取历史数据
    from binance import AsyncClient
    binance_async = await AsyncClient.create()
    
    try:
        limit = min(1000, days * (24 if interval == "1h" else 96))
        history_data = await binance_async.get_klines(symbol=bot.symbol, interval=interval, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"行情获取失败: {str(e)}")
    finally:
        await binance_async.close_connection()

    if not history_data:
        raise HTTPException(status_code=500, detail="无法获取该币种的历史行情数据")

    # 4. 初始化并运行回测引擎
    engine = BacktestEngine(strategy_class, bot)
    results = await engine.run(history_data)
    
    return results
