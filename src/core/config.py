import base64

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base
    PROJECT_NAME: str = "BinanceBot V3.0"
    VERSION: str = "3.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # Security
    MASTER_ENCRYPTION_KEY: str = Field(
        ...,
        description="Master key for DEK encryption. 32 bytes base64 encoded.",
    )
    JWT_SECRET_KEY: str = Field(..., description="Secret key for JWT generation.")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    ALLOW_LIVE_TRADING: bool = False

    # Database
    DATABASE_URL: str = Field(..., description="PostgreSQL async connection string")
    REDIS_URL: str = Field(..., description="Redis connection string")

    # Exchange
    BINANCE_TESTNET: bool = True
    IGNORE_GEO_CHECK: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @staticmethod
    def _strip_wrapping_quotes(value: str | None) -> str:
        if value is None:
            return ""
        return str(value).strip().strip("'\"")

    @staticmethod
    def mask_secret(value: str | None, reveal_chars: int = 4) -> str:
        cleaned = Settings._strip_wrapping_quotes(value)
        if not cleaned:
            return "****"
        if len(cleaned) <= reveal_chars:
            return "****"
        return f"****{cleaned[-reveal_chars:]}"

    @field_validator(
        "MASTER_ENCRYPTION_KEY",
        "JWT_SECRET_KEY",
        "DATABASE_URL",
        "REDIS_URL",
        mode="before",
    )
    @classmethod
    def _sanitize_string_settings(cls, value: str) -> str:
        return cls._strip_wrapping_quotes(value)

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _normalize_environment(cls, value: str) -> str:
        normalized = cls._strip_wrapping_quotes(value).lower() or "development"
        allowed = {"development", "staging", "production", "test"}
        if normalized not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = cls._strip_wrapping_quotes(value).upper() or "INFO"
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of: {', '.join(sorted(allowed))}")
        return normalized

    @field_validator("MASTER_ENCRYPTION_KEY")
    @classmethod
    def _validate_master_encryption_key(cls, value: str) -> str:
        try:
            decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
        except Exception as exc:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY must be a valid url-safe base64 encoded value"
            ) from exc

        if len(decoded) != 32:
            raise ValueError(
                "MASTER_ENCRYPTION_KEY must decode to exactly 32 bytes for Fernet compatibility"
            )

        return value

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _validate_jwt_secret(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters long")
        return value

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def assert_trading_allowed(self, *, is_testnet: bool) -> None:
        if not is_testnet and not self.ALLOW_LIVE_TRADING:
            raise ValueError(
                "Live mainnet trading is disabled by configuration. "
                "Set ALLOW_LIVE_TRADING=true only after completing a production safety review."
            )


# Global settings instance
settings = Settings()