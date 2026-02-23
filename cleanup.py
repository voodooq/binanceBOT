import asyncio
import os
import logging
from decimal import Decimal
from src.config.binance_config import loadSettings
from src.exchanges.binance_client import BinanceClient
from src.utils.rate_limiter import RateLimiter
from src.utils.logger import setupLogger

async def cleanup():
    # 1. 加载配置与日志
    settings = loadSettings()
    setupLogger(logLevel="INFO")
    logger = logging.getLogger("cleanup")
    
    if not settings.useTestnet:
        logger.info("🛡️ 当前为正式网环境，跳过战前清理以保护真实订单。")
        return

    logger.info("🧹 开始清理测试网环境...")
    
    # 2. 初始化速率限制器与客户端
    rateLimiter = RateLimiter()
    client = BinanceClient(settings, rateLimiter)
    
    try:
        # 3. 建立连接 (必须调用 connect 以初始化底层 aiohttp session)
        await client.connect()
        
        # 4. 检查余额
        usdt_balance = await client.getFreeBalance("USDT")
        bnb_balance = await client.getFreeBalance("BNB")
        logger.info(f"💰 当前余额: {usdt_balance} USDT, {bnb_balance} BNB")
        
        # 5. 撤销所有挂单
        logger.info(f"🚫 正在撤销 {settings.tradingSymbol} 的所有挂单...")
        await client.nuke_all_orders()
        
        # 6. 打印最终状态
        logger.info("🎉 环境清理完成！现在你可以安全启动机器人了。")
        
    except Exception as e:
        logger.error(f"❌ 清理失败: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # 确保异步客户端正确关闭 (V3.0 接口名由 close 改为 disconnect)
        await client.disconnect()

if __name__ == "__main__":
    # 设置代理环境
    settings = loadSettings()
    if settings.proxyUrl:
        os.environ["HTTPS_PROXY"] = settings.proxyUrl
        os.environ["HTTP_PROXY"] = settings.proxyUrl
        
    asyncio.run(cleanup())
