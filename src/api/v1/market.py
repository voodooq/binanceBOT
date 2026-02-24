from fastapi import APIRouter, HTTPException, Query
from binance import AsyncClient
from binance.exceptions import BinanceAPIException
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/price")
async def get_market_price(symbol: str = Query("BTCUSDT", description="交易对，如 BTCUSDT")):
    """
    获取指定交易对的当前公开市场价格。
    用于在前端创建机器人时提供基准计算建议网格参数。
    """
    client = await AsyncClient.create() # 公共端点无需 API Key
    try:
        ticker = await client.get_symbol_ticker(symbol=symbol.upper())
        return {
            "symbol": ticker["symbol"],
            "price": ticker["price"]
        }
    except BinanceAPIException as e:
        logger.error(f"Failed to fetch market price for {symbol}: {e}")
        raise HTTPException(status_code=400, detail=f"无法获取该交易对价格: {e.message}")
    finally:
        await client.close_connection()
