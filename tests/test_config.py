"""
配置加载模块单元测试
"""
import os
import tempfile
from decimal import Decimal

import pytest

from src.config.binance_config import Settings, loadSettings, _maskSecret


class TestMaskSecret:
    """敏感信息脱敏函数测试"""

    def test_normalString(self) -> None:
        assert _maskSecret("abcdefgh12345678") == "****5678"

    def test_shortString(self) -> None:
        assert _maskSecret("abc") == "****"

    def test_emptyString(self) -> None:
        assert _maskSecret("") == "****"

    def test_exactlyFourChars(self) -> None:
        assert _maskSecret("abcd") == "****"

    def test_fiveChars(self) -> None:
        assert _maskSecret("abcde") == "****bcde"


class TestSettings:
    """Settings 数据类测试"""

    def test_defaultValues(self) -> None:
        """默认值应合理"""
        s = Settings()
        assert s.tradingSymbol == "BTCUSDT"
        assert s.useTestnet is True
        assert s.gridCount == 10

    def test_testnetUrls(self) -> None:
        """测试网模式下应使用测试网 URL"""
        s = Settings(useTestnet=True)
        assert "testnet" in s.baseUrl
        assert "testnet" in s.wsBaseUrl

    def test_mainnetUrls(self) -> None:
        """主网模式下应使用主网 URL"""
        s = Settings(useTestnet=False)
        assert "api.binance.com" in s.baseUrl
        assert "stream.binance.com" in s.wsBaseUrl

    def test_validateMissingApiKey(self) -> None:
        """缺失 API Key 应抛出 ValueError"""
        s = Settings(apiKey="", apiSecret="real_secret_here_xyz")
        with pytest.raises(ValueError, match="API Key"):
            s.validate()

    def test_validatePlaceholderApiKey(self) -> None:
        """占位符 API Key 应抛出 ValueError"""
        s = Settings(apiKey="your_api_key_here", apiSecret="real_secret")
        with pytest.raises(ValueError, match="API Key"):
            s.validate()

    def test_validateInvalidGridRange(self) -> None:
        """网格上界 ≤ 下界应抛出 ValueError"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
            gridUpperPrice=Decimal("50000"),
            gridLowerPrice=Decimal("60000"),
        )
        with pytest.raises(ValueError, match="上界"):
            s.validate()

    def test_validateInvalidGridCount(self) -> None:
        """网格数量 < 2 应抛出 ValueError"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
            gridCount=1,
        )
        with pytest.raises(ValueError, match="网格数量"):
            s.validate()

    def test_validateInvalidStopLoss(self) -> None:
        """止损百分比超出 0~1 范围应抛出 ValueError"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
            stopLossPercent=Decimal("1.5"),
        )
        with pytest.raises(ValueError, match="止损"):
            s.validate()

    def test_validateSuccess(self) -> None:
        """合法配置应通过校验"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
        )
        # 不应抛出异常
        s.validate()


class TestLoadSettings:
    """配置文件加载测试"""

    def test_missingEnvFile(self) -> None:
        """不存在的 .env 文件应抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError, match=".env"):
            loadSettings(envPath="/nonexistent/path/.env")

    def test_loadFromFile(self) -> None:
        """应能从临时 .env 文件正确加载配置"""
        envContent = (
            "BINANCE_API_KEY=test_key_12345\n"
            "BINANCE_API_SECRET=test_secret_67890\n"
            "USE_TESTNET=true\n"
            "TRADING_SYMBOL=ETHUSDT\n"
            "GRID_COUNT=5\n"
            "GRID_UPPER_PRICE=4000\n"
            "GRID_LOWER_PRICE=3000\n"
        )

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".env", delete=False
        ) as f:
            f.write(envContent)
            tmpPath = f.name

        try:
            settings = loadSettings(envPath=tmpPath)
            assert settings.apiKey == "test_key_12345"
            assert settings.apiSecret == "test_secret_67890"
            assert settings.useTestnet is True
            assert settings.tradingSymbol == "ETHUSDT"
            assert settings.gridCount == 5
            assert settings.gridUpperPrice == Decimal("4000")
            assert settings.gridLowerPrice == Decimal("3000")
        finally:
            os.unlink(tmpPath)

    def test_validateGridCountExceedsMaxOrders(self) -> None:
        """网格数量超过最大挂单数应抛出 ValueError"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
            gridCount=150,
            maxOrderCount=100,
        )
        with pytest.raises(ValueError, match="网格数量"):
            s.validate()

    def test_validateGridCountWithinLimit(self) -> None:
        """网格数量不超过最大挂单数应通过校验"""
        s = Settings(
            apiKey="real_key_1234",
            apiSecret="real_secret_1234",
            gridCount=50,
            maxOrderCount=100,
        )
        # 不应抛出异常
        s.validate()

