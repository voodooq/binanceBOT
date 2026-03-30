from typing import Any

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_current_user
from src.db.session import get_db
from src.models.api_key import ApiKey
from src.models.user import User
from src.services.crypto_service import crypto_service

logger = logging.getLogger(__name__)

SUPPORTED_EXCHANGES = {"binance"}


def _mask_api_key(value: str) -> str:
    cleaned = (value or "").strip()
    if len(cleaned) <= 4:
        return "****"
    return f"****{cleaned[-4:]}"


class ApiKeyCreate(BaseModel):
    exchange: str = "binance"
    api_key: str = Field(..., min_length=8, max_length=255)
    api_secret: str = Field(..., min_length=8, max_length=255)
    is_testnet: bool = False

    @field_validator("exchange", mode="before")
    @classmethod
    def validate_exchange(cls, value: str) -> str:
        normalized = (value or "binance").strip().lower()
        if normalized not in SUPPORTED_EXCHANGES:
            raise ValueError(f"Unsupported exchange: {normalized}")
        return normalized

    @field_validator("api_key", "api_secret", mode="before")
    @classmethod
    def validate_secret_like_fields(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Credential value cannot be empty")
        return cleaned


class ApiKeyResponse(BaseModel):
    id: int
    exchange: str
    api_key: str
    is_testnet: bool

    model_config = ConfigDict(from_attributes=True)


router = APIRouter()


def _to_response(api_key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=api_key.id,
        exchange=api_key.exchange,
        api_key=_mask_api_key(api_key.api_key),
        is_testnet=api_key.is_testnet,
    )


@router.post("/", response_model=ApiKeyResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    key_in: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """绑定新的交易所 API Key。私钥将被用户的信封密钥 (DEK) 加密存储"""
    normalized_api_key = key_in.api_key.strip()

    stmt = select(ApiKey).where(
        ApiKey.user_id == current_user.id,
        ApiKey.exchange == key_in.exchange,
        ApiKey.api_key == normalized_api_key,
    )
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="此 API Key 已经绑定")

    user_has_existing_keys_stmt = select(ApiKey.id).where(ApiKey.user_id == current_user.id)
    user_has_existing_keys = bool((await db.execute(user_has_existing_keys_stmt)).first())

    encrypted_dek = current_user.encrypted_dek
    if not encrypted_dek:
        if user_has_existing_keys:
            logger.error("User %s is missing DEK while historical API keys exist", current_user.id)
            raise HTTPException(status_code=500, detail="账号加密上下文异常，请联系管理员处理")
        _, encrypted_dek = crypto_service.generate_user_dek()
        current_user.encrypted_dek = encrypted_dek
        db.add(current_user)

    try:
        encrypted_secret = crypto_service.encrypt_secret_with_dek(
            encrypted_dek_b64=encrypted_dek,
            secret_str=key_in.api_secret,
        )
    except ValueError:
        if user_has_existing_keys:
            logger.error("User %s has invalid DEK while historical API keys exist", current_user.id)
            raise HTTPException(status_code=500, detail="账号加密上下文异常，请联系管理员处理")

        logger.warning("Resetting invalid DEK for user %s without historical API keys", current_user.id)
        _, new_encrypted_dek = crypto_service.generate_user_dek()
        current_user.encrypted_dek = new_encrypted_dek
        db.add(current_user)

        try:
            encrypted_secret = crypto_service.encrypt_secret_with_dek(
                encrypted_dek_b64=new_encrypted_dek,
                secret_str=key_in.api_secret,
            )
        except ValueError as exc:
            logger.error("Failed to rebuild encryption context for user %s", current_user.id)
            raise HTTPException(status_code=500, detail="无法建立安全加密环境") from exc
    except Exception as exc:
        logger.exception("Unexpected failure during API credential encryption")
        raise HTTPException(status_code=500, detail="加密处理异常") from exc

    new_key = ApiKey(
        user_id=current_user.id,
        exchange=key_in.exchange,
        api_key=normalized_api_key,
        encrypted_secret=encrypted_secret,
        is_testnet=key_in.is_testnet,
    )

    db.add(new_key)
    await db.commit()
    await db.refresh(new_key)
    return _to_response(new_key)


@router.get("/", response_model=list[ApiKeyResponse])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """列出当前用户绑定的所有凭证"""
    stmt = select(ApiKey).where(ApiKey.user_id == current_user.id).order_by(ApiKey.id.desc())
    result = await db.execute(stmt)
    return [_to_response(item) for item in result.scalars().all()]