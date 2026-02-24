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

    def __init__(self, **values):
        super().__init__(**values)
        # 容错处理：自动剥离可能误带的引号
        self.MASTER_ENCRYPTION_KEY = self.MASTER_ENCRYPTION_KEY.strip("'\"")
        self.JWT_SECRET_KEY = self.JWT_SECRET_KEY.strip("'\"")
        self.DATABASE_URL = self.DATABASE_URL.strip("'\"")
        self.REDIS_URL = self.REDIS_URL.strip("'\"")

# Global settings instance
settings = Settings()

