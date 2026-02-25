from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.session import get_db
from src.api.dependencies import get_current_user
from src.models.user import User
from src.models.api_key import ApiKey
from src.services.crypto_service import crypto_service
import logging

logger = logging.getLogger(__name__)

class ApiKeyCreate(BaseModel):
    exchange: str = "binance"
    api_key: str = Field(..., max_length=255)
    api_secret: str = Field(..., max_length=255)
    is_testnet: bool = False

class ApiKeyResponse(BaseModel):
    id: int
    exchange: str
    api_key: str
    is_testnet: bool

    model_config = ConfigDict(from_attributes=True)

router = APIRouter()


@router.post("/", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """绑定新的交易所 API Key。私钥将被用户的信封密钥 (DEK) 加密存储"""
    
    # 检查当前用户的公钥是否已重复绑定
    stmt = select(ApiKey).where(ApiKey.user_id == current_user.id, ApiKey.api_key == key_in.api_key)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="此 API Key 已经绑定")

    # 使用用户的加密上下文解密得到 DEK 原始字节串，再用 DEK 对目标秘钥执行信封加密
    try:
        if not current_user.encrypted_dek:
            # 强制触发自愈逻辑
            raise ValueError("Invalid DEK (Empty)")

        encrypted_secret = crypto_service.encrypt_secret_with_dek(
            encrypted_dek_b64=current_user.encrypted_dek,
            secret_str=key_in.api_secret
        )
    except Exception as e:
        logger.warning(f"Encryption failed for user {current_user.id}: {str(e)}. Attempting self-healing...")
        # 自愈逻辑：如果解密失败且用户没有 API Key，则尝试自动重新生成并保存新的 DEK
        # 这一步能解决之前 Master Key 变更导致老账号 500 的问题
        if isinstance(e, ValueError) or "Invalid DEK" in str(e) or not current_user.encrypted_dek:
            # 检查用户是否已有绑定的 Key，如有则不能自愈（防止误删导致数据彻底无法解密）
            stmt = select(ApiKey).where(ApiKey.user_id == current_user.id)
            existing_count = await db.execute(stmt)
            if not existing_count.scalars().first():
                logger.info(f"Resetting invalid/missing DEK for user {current_user.id}")
                # 重新生成 DEK 并保存
                try:
                    plain_dek, new_encrypted_dek = crypto_service.generate_user_dek()
                    current_user.encrypted_dek = new_encrypted_dek
                    db.add(current_user)
                    # 重新尝试加密
                    encrypted_secret = crypto_service.encrypt_secret_with_dek(
                        encrypted_dek_b64=new_encrypted_dek,
                        secret_str=key_in.api_secret
                    )
                except Exception as fatal_e:
                    logger.error(f"Self-healing failed: {fatal_e}")
                    raise HTTPException(status_code=500, detail=f"无法恢复加密环境: {fatal_e}")
            else:
                logger.error(f"DEK invalid but user has existing keys. Cannot auto-reset.")
                raise HTTPException(status_code=500, detail="解密密钥失效且账号已绑定数据，请联系管理员或清理环境")
        else:
            logger.exception("Unexpected error during API Key encryption")
            raise HTTPException(status_code=500, detail=f"加密处理异常: {str(e)}")

    new_key = ApiKey(
        user_id=current_user.id,
        exchange=key_in.exchange,
        api_key=key_in.api_key,
        encrypted_secret=encrypted_secret,
        is_testnet=key_in.is_testnet
    )

    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    return new_key

@router.get("/", response_model=list[ApiKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """列出当前用户绑定的所有凭证"""
    stmt = select(ApiKey).where(ApiKey.user_id == current_user.id)
    result = await db.execute(stmt)
    return result.scalars().all()
