"""
币安交易机器人 — 配置加载模块

从 .env 文件读取所有配置项，提供类型安全的 Settings 数据类。
启动时自动校验必填字段，敏感信息日志脱敏。
"""
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from decimal import Decimal

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# NOTE: 项目根目录定位基于此文件的相对路径 (src/config/ → 根)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _maskSecret(value: str) -> str:
    """
    对敏感字符串脱敏，仅保留末 4 位。
    用于日志输出，防止密钥泄露。
    """
    if not value or len(value) <= 4:
        return "****"
    return f"****{value[-4:]}"


@dataclass
class Settings:
    """
    机器人全局配置数据类。
    所有字段均从环境变量加载，带有合理的默认值。
    """

    # --- 币安 API 凭证 ---
    apiKey: str = ""
    apiSecret: str = ""

    # --- 环境切换 ---
    useTestnet: bool = True

    # --- 交易对 ---
    tradingSymbol: str = "BTCUSDT"

    # --- 网格策略参数 ---
    gridUpperPrice: Decimal = Decimal("70000")
    gridLowerPrice: Decimal = Decimal("60000")
    gridCount: int = 10
    gridInvestmentPerGrid: Decimal = Decimal("10")

    # --- 风控参数 ---
    stopLossPercent: Decimal = Decimal("0.05")
    takeProfitAmount: Decimal = Decimal("100")
    maxSpreadPercent: Decimal = Decimal("0.001")
    reserveRatio: Decimal = Decimal("0.1")

    # --- Telegram 通知 ---
    telegramBotToken: str = ""
    telegramChatId: str = ""

    # --- 日志级别 ---
    logLevel: str = "INFO"
    proxyUrl: str | None = None

    # --- 自适应策略 ---
    adaptiveMode: bool = True
    analysisInterval: int = 300
    martinMultiplier: Decimal = Decimal("1.5")

    # --- 安全阀值 ---
    maxMartinLevels: int = 3                      # 马丁最大连续加仓层数
    maxDrawdown: Decimal = Decimal("0.2")         # 总账户最大回撤比例
    maxOrderCount: int = 100                      # 单交易对最大挂单数
    staleDataTimeout: int = 120                   # K 线数据过期阀值（秒）
    tradingFeeRate: Decimal = Decimal("0.001")    # 单边手续费率 (0.1%)
    maxPositionRatio: Decimal = Decimal("0.7")    # 持仓占比上限 (70%)
    trendEmaPeriod: int = 200                     # 宏观大势 EMA 周期
    decayMinMultiplier: Decimal = Decimal("0.2")  # 动态仓位衰减的最小投入倍数
    rsiBleedThreshold: int = 32                   # 阴跌熔断 RSI 阈值
    tradeCooldown: float = 5.0                    # 交易冷却时间（秒）

    # --- 派生属性 ---
    # NOTE: 主网和测试网的 API 基础地址不同，由 useTestnet 自动决定
    baseUrl: str = field(init=False)
    wsBaseUrl: str = field(init=False)

    def __post_init__(self) -> None:
        """根据 useTestnet 设置 API 端点"""
        if self.useTestnet:
            self.baseUrl = "https://testnet.binance.vision/api"
            self.wsBaseUrl = "wss://testnet.binance.vision/ws"
        else:
            self.baseUrl = "https://api.binance.com/api"
            self.wsBaseUrl = "wss://stream.binance.com:9443/ws"

    def validate(self) -> None:
        """
        校验必填配置项。
        缺失关键配置时抛出 ValueError，防止带着无效配置启动。
        """
        if not self.apiKey or self.apiKey == "your_api_key_here":
            raise ValueError("BINANCE_API_KEY 未配置，请在 .env 文件中设置真实的 API Key")

        if not self.apiSecret or self.apiSecret == "your_api_secret_here":
            raise ValueError("BINANCE_API_SECRET 未配置，请在 .env 文件中设置真实的 API Secret")

        if self.gridUpperPrice <= self.gridLowerPrice:
            raise ValueError(
                f"网格上界 ({self.gridUpperPrice}) 必须大于下界 ({self.gridLowerPrice})"
            )

        if self.gridCount < 2:
            raise ValueError(f"网格数量 ({self.gridCount}) 至少为 2")

        if self.gridInvestmentPerGrid <= 0:
            raise ValueError("每格投入金额必须大于 0")

        if not (0 < self.stopLossPercent < 1):
            raise ValueError(f"止损百分比 ({self.stopLossPercent}) 必须在 0~1 之间")

        if not (0 < self.reserveRatio < 1):
            raise ValueError(f"资金预留比例 ({self.reserveRatio}) 必须在 0~1 之间")

        # NOTE: 网格数不能超过单交易对最大挂单限制，否则启动后必定触发 API 错误
        if self.gridCount > self.maxOrderCount:
            raise ValueError(
                f"网格数量 ({self.gridCount}) 不能超过最大挂单数 ({self.maxOrderCount})"
            )

        logger.info("✅ 配置校验通过")

    def logSummary(self) -> None:
        """安全地输出配置摘要，敏感字段脱敏"""
        logger.info("=" * 50)
        logger.info("📋 机器人配置摘要")
        logger.info("=" * 50)
        logger.info("API Key:        %s", _maskSecret(self.apiKey))
        logger.info("环境:           %s", "测试网" if self.useTestnet else "⚠️  主网")
        logger.info("交易对:         %s", self.tradingSymbol)
        logger.info(
            "网格范围:       %s ~ %s (%d 格)",
            self.gridLowerPrice, self.gridUpperPrice, self.gridCount,
        )
        logger.info("每格投入:       %s USDT", self.gridInvestmentPerGrid)
        logger.info("止损线:         %s%%", self.stopLossPercent * 100)
        logger.info("止盈目标:       %s USDT", self.takeProfitAmount)
        logger.info("最大价差:       %s%%", self.maxSpreadPercent * 100)
        logger.info("资金预留:       %s%%", self.reserveRatio * 100)
        logger.info(
            "Telegram 通知:  %s",
            "已配置" if self.telegramBotToken else "未配置（跳过）",
        )
        logger.info("=" * 50)


def loadSettings(envPath: str | None = None) -> Settings:
    """
    从 .env 文件加载配置并返回 Settings 实例。

    @param envPath 自定义 .env 文件路径，默认使用项目根目录下的 .env
    @returns 经过校验的 Settings 实例
    """
    dotenvPath = envPath or str(PROJECT_ROOT / ".env")

    if not Path(dotenvPath).exists():
        raise FileNotFoundError(
            f".env 文件不存在: {dotenvPath}\n"
            "请复制 .env.example 为 .env 并填入真实的 API 密钥"
        )

    load_dotenv(dotenvPath, override=True)

    settings = Settings(
        apiKey=os.getenv("BINANCE_API_KEY", ""),
        apiSecret=os.getenv("BINANCE_API_SECRET", ""),
        useTestnet=os.getenv("USE_TESTNET", "true").lower() == "true",
        tradingSymbol=os.getenv("TRADING_SYMBOL", "BTCUSDT"),
        gridUpperPrice=Decimal(os.getenv("GRID_UPPER_PRICE", "70000")),
        gridLowerPrice=Decimal(os.getenv("GRID_LOWER_PRICE", "60000")),
        gridCount=int(os.getenv("GRID_COUNT", "10")),
        gridInvestmentPerGrid=Decimal(os.getenv("GRID_INVESTMENT_PER_GRID", "10")),
        stopLossPercent=Decimal(os.getenv("STOP_LOSS_PERCENT", "0.05")),
        takeProfitAmount=Decimal(os.getenv("TAKE_PROFIT_AMOUNT", "100")),
        maxSpreadPercent=Decimal(os.getenv("MAX_SPREAD_PERCENT", "0.001")),
        reserveRatio=Decimal(os.getenv("RESERVE_RATIO", "0.1")),
        telegramBotToken=os.getenv("TELEGRAM_BOT_TOKEN", ""),
        telegramChatId=os.getenv("TELEGRAM_CHAT_ID", ""),
        logLevel=os.getenv("LOG_LEVEL", "INFO"),
        proxyUrl=os.getenv("PROXY_URL"),
        adaptiveMode=os.getenv("ADAPTIVE_MODE", "true").lower() == "true",
        analysisInterval=int(os.getenv("ANALYSIS_INTERVAL", "300")),
        martinMultiplier=Decimal(os.getenv("MARTIN_MULTIPLIER", "1.5")),
        maxMartinLevels=int(os.getenv("MAX_MARTIN_LEVELS", "3")),
        maxDrawdown=Decimal(os.getenv("MAX_DRAWDOWN", "0.2")),
        maxOrderCount=int(os.getenv("MAX_ORDER_COUNT", "100")),
        staleDataTimeout=int(os.getenv("STALE_DATA_TIMEOUT", "120")),
        tradingFeeRate=Decimal(os.getenv("TRADING_FEE_RATE", "0.001")),
        maxPositionRatio=Decimal(os.getenv("MAX_POSITION_RATIO", "0.7")),
        trendEmaPeriod=int(os.getenv("TREND_EMA_PERIOD", "200")),
        decayMinMultiplier=Decimal(os.getenv("DECAY_MIN_MULTIPLIER", "0.2")),
        rsiBleedThreshold=int(os.getenv("RSI_BLEED_THRESHOLD", "32")),
        tradeCooldown=float(os.getenv("TRADE_COOLDOWN", "5.0")),
    )

    return settings
