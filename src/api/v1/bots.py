from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.db.session import get_db
from src.api.dependencies import get_current_user
from src.models.user import User
from src.models.bot import BotConfig, BotStatus
from src.schemas.bot import BotConfigCreate, BotConfigUpdate, BotConfigResponse
from src.engine.strategy_manager import strategy_manager
from src.services.crypto_service import crypto_service
from src.models.api_key import ApiKey

router = APIRouter()

@router.post("/", response_model=BotConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_bot(
    bot_in: BotConfigCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """创建新的机器人配置"""
    # 验证 API Key 是否属于该用户
    query = select(ApiKey).where(ApiKey.id == bot_in.api_key_id, ApiKey.user_id == current_user.id)
    result = await db.execute(query)
    api_key = result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(status_code=404, detail="绑定的 API Key 不存在或无权访问")
        
    bot_config = BotConfig(
        user_id=current_user.id,
        api_key_id=bot_in.api_key_id,
        name=bot_in.name,
        symbol=bot_in.symbol,
        strategy_type=bot_in.strategy_type,
        parameters=bot_in.parameters,
        base_asset=bot_in.base_asset,
        quote_asset=bot_in.quote_asset,
        total_investment=bot_in.total_investment,
        is_testnet=bot_in.is_testnet,
        status=BotStatus.IDLE
    )
    db.add(bot_config)
    await db.commit()
    await db.refresh(bot_config)
    return bot_config

@router.get("/", response_model=list[BotConfigResponse])
async def list_bots(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    api_key_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """获取用户的机器人列表"""
    query = select(BotConfig).where(BotConfig.user_id == current_user.id)
    if api_key_id is not None:
        query = query.where(BotConfig.api_key_id == api_key_id)
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()

@router.post("/{bot_id}/start")
async def start_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """在后台拉起某个机器人的运行实例"""
    query = select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == current_user.id)
    result = await db.execute(query)
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(status_code=404, detail="未找到该机器人")
    
    if bot.status == BotStatus.RUNNING:
        raise HTTPException(status_code=400, detail="该机器人已在运行中")

    # 获取关联的 API Key 和解密
    query_key = select(ApiKey).where(ApiKey.id == bot.api_key_id)
    key_result = await db.execute(query_key)
    api_key = key_result.scalar_one_or_none()
    
    if not api_key:
        raise HTTPException(status_code=400, detail="绑定的 API Key 已被删除")
        
    try:
        # NOTE: 使用 CryptoService 的正确方法签名
        api_secret_str = crypto_service.decrypt_user_secret(
            current_user.encrypted_dek, api_key.encrypted_secret
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="解密 API Secret 失败，请检查 DEK 连通性")

        
    # 调用大盘 StrategyManager 调度此实例
    success = await strategy_manager.start_bot(bot, api_key_str=api_key.api_key, api_secret_str=api_secret_str)
    
    if success:
        bot.status = BotStatus.RUNNING
        await db.commit()
        return {"msg": "Bot 已成功启动"}
    else:
        bot.status = BotStatus.ERROR
        await db.commit()
        raise HTTPException(status_code=500, detail="拉起运行时环境失败，请查看引擎日志")

@router.post("/{bot_id}/stop")
async def stop_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """挂起或安全停止指定的机器人"""
    query = select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == current_user.id)
    result = await db.execute(query)
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(status_code=404, detail="未找到该机器人")
        
    success = await strategy_manager.stop_bot(bot.id)
    
    # 无论引擎是否真的在跑这只 bot（可能是容器重启导致的 DB 保存了残魂 RUNNING 态）
    # 都把它的名份给清理成停止，以便允许用户接下来的操作。
    bot.status = BotStatus.STOPPED
    await db.commit()

    if success:
        return {"msg": "Bot 已停止工作并清理挂单"}
    else:
        return {"msg": "Bot 引擎中未发现活跃运行态，已强制重置数据库状态为停止"}

@router.get("/{bot_id}", response_model=BotConfigResponse)
async def get_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Any:
    """获取单个机器人配置详情"""
    query = select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == current_user.id)
    result = await db.execute(query)
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(status_code=404, detail="未找到该机器人")
    return bot

@router.delete("/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bot(
    bot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """强制删除机器人"""
    query = select(BotConfig).where(BotConfig.id == bot_id, BotConfig.user_id == current_user.id)
    result = await db.execute(query)
    bot = result.scalar_one_or_none()
    
    if not bot:
        raise HTTPException(status_code=404, detail="未找到该机器人")
        
    if bot.status == BotStatus.RUNNING:
        raise HTTPException(status_code=400, detail="请先停止运行中的机器人后再删除")
        
    await db.delete(bot)
    await db.commit()
