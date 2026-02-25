from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from typing import List

from src.db.session import get_db
from src.api.dependencies import get_current_user
from src.models.user import User
from src.models.notification import Notification, NotificationSetting, NotificationLevel

router = APIRouter()

@router.get("/")
async def get_notifications(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的通知历史流水"""
    stmt = select(Notification).where(
        Notification.user_id == current_user.id
    ).order_by(Notification.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return result.scalars().all()

@router.post("/{notif_id}/read")
async def mark_as_read(
    notif_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """将通知标记为已读"""
    stmt = update(Notification).where(
        Notification.id == notif_id, 
        Notification.user_id == current_user.id
    ).values(is_read=True)
    await db.execute(stmt)
    await db.commit()
    return {"status": "success"}

@router.get("/settings")
async def get_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询用户通知偏好设置"""
    stmt = select(NotificationSetting).where(NotificationSetting.user_id == current_user.id)
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if not setting:
        # 默认初始化
        setting = NotificationSetting(user_id=current_user.id)
        db.add(setting)
        await db.commit()
        await db.refresh(setting)
        
    return setting

@router.put("/settings")
async def update_settings(
    settings_data: dict,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新用户通知偏好设置 (渠道与等级)"""
    stmt = select(NotificationSetting).where(NotificationSetting.user_id == current_user.id)
    result = await db.execute(stmt)
    setting = result.scalar_one_or_none()
    
    if not setting:
        setting = NotificationSetting(user_id=current_user.id)
        db.add(setting)

    # 安全地映射字段
    allowed_fields = ["telegram_enabled", "email_enabled", "web_enabled", "min_level", "telegram_chat_id", "email_address"]
    for field in allowed_fields:
        if field in settings_data:
            setattr(setting, field, settings_data[field])
            
    await db.commit()
    return {"status": "success"}
