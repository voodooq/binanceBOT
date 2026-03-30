"""
当前运行时配置模块单元测试
"""
import os

import pytest
from pydantic import ValidationError

VALID_MASTER_KEY = "oG-Wpv8mY_hF4rNn9sJzG_t_R9LpX_Vz8K-Q5v-E3uA="
VALID_JWT_SECRET = "Sgh7gItcOrn7wbDImoq4EnW58AZDGgQZ8zUAzGgD2HMg5scxwjNn9o0RcW9TDlsp"
VALID_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/binancebot"
VALID_REDIS_URL = "redis://127.0.0.1:6379/0"

os.environ.setdefault("MASTER_ENCRYPTION_KEY", VALID_MASTER_KEY)
os.environ.setdefault("JWT_SECRET_KEY", VALID_JWT_SECRET)
os.environ.setdefault("DATABASE_URL", VALID_DATABASE_URL)
os.environ.setdefault("REDIS_URL", VALID_REDIS_URL)

from src.core.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "MASTER_ENCRYPTION_KEY": VALID_MASTER_KEY,
        "JWT_SECRET_KEY": VALID_JWT_SECRET,
        "DATABASE_URL": VALID_DATABASE_URL,
        "REDIS_URL": VALID_REDIS_URL,
        "ENVIRONMENT": "development",
        "LOG_LEVEL": "INFO",
        "ALLOW_LIVE_TRADING": False,
        "BINANCE_TESTNET": True,
        "IGNORE_GEO_CHECK": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestMaskSecret:
    """敏感信息脱敏测试"""

    def test_normal_string(self) -> None:
        assert Settings.mask_secret("abcdefgh12345678") == "****5678"

    def test_short_string(self) -> None:
        assert Settings.mask_secret("abc") == "****"

    def test_empty_string(self) -> None:
        assert Settings.mask_secret("") == "****"

    def test_quoted_string(self) -> None:
        assert Settings.mask_secret('"abcdefgh12345678"') == "****5678"


class TestSettingsValidation:
    """Settings 校验测试"""

    def test_default_like_values(self) -> None:
        settings = _make_settings()
        assert settings.ENVIRONMENT == "development"
        assert settings.LOG_LEVEL == "INFO"
        assert settings.ALLOW_LIVE_TRADING is False
        assert settings.BINANCE_TESTNET is True

    def test_strip_wrapping_quotes(self) -> None:
        settings = _make_settings(
            MASTER_ENCRYPTION_KEY=f'"{VALID_MASTER_KEY}"',
            JWT_SECRET_KEY=f"'{VALID_JWT_SECRET}'",
            DATABASE_URL=f'"{VALID_DATABASE_URL}"',
            REDIS_URL=f"'{VALID_REDIS_URL}'",
        )
        assert settings.MASTER_ENCRYPTION_KEY == VALID_MASTER_KEY
        assert settings.JWT_SECRET_KEY == VALID_JWT_SECRET
        assert settings.DATABASE_URL == VALID_DATABASE_URL
        assert settings.REDIS_URL == VALID_REDIS_URL

    def test_invalid_environment_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(ENVIRONMENT="prod-like")

    def test_invalid_log_level_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(LOG_LEVEL="TRACE")

    def test_invalid_master_key_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(MASTER_ENCRYPTION_KEY="not-a-valid-key")

    def test_short_jwt_secret_raises(self) -> None:
        with pytest.raises(ValidationError):
            _make_settings(JWT_SECRET_KEY="short-secret")

    def test_is_production_property(self) -> None:
        settings = _make_settings(ENVIRONMENT="production")
        assert settings.is_production is True

    def test_assert_trading_allowed_for_testnet(self) -> None:
        settings = _make_settings(ALLOW_LIVE_TRADING=False)
        settings.assert_trading_allowed(is_testnet=True)

    def test_assert_trading_allowed_blocks_mainnet_by_default(self) -> None:
        settings = _make_settings(ALLOW_LIVE_TRADING=False)
        with pytest.raises(ValueError, match="Live mainnet trading is disabled"):
            settings.assert_trading_allowed(is_testnet=False)

    def test_assert_trading_allowed_accepts_mainnet_when_enabled(self) -> None:
        settings = _make_settings(ALLOW_LIVE_TRADING=True)
        settings.assert_trading_allowed(is_testnet=False)