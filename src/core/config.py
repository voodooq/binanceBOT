from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # Base
    PROJECT_NAME: str = "BinanceBot V3.0"
    VERSION: str = "3.0.0"
    API_V1_STR: str = "/api/v1"
    
    # Security
    MASTER_ENCRYPTION_KEY: str = Field(..., description="Master key for DEK encryption. 32 bytes base64 encoded.")
    JWT_SECRET_KEY: str = Field(..., description="Secret key for JWT generation.")
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7 # 7 days
    
    # Database
    DATABASE_URL: str = Field(..., description="PostgreSQL async connection string")
    REDIS_URL: str = Field(..., description="Redis connection string")
    
    # Exchange
    BINANCE_TESTNET: bool = True
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

# Global settings instance
settings = Settings()
