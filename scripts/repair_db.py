import asyncio
import os
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# 尝试从环境变量获取数据库 URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:B1nAnc3B0t_Str0ng_P4ssw0rd!@127.0.0.1:5432/binancebot")

async def repair():
    print(f"Connecting to database: {DATABASE_URL}")
    engine = create_async_engine(DATABASE_URL)
    
    async with engine.begin() as conn:
        # 1. 检查 notification_settings 表是否存在 id 列
        result = await conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'notification_settings' AND column_name = 'id';
        """))
        has_id = result.fetchone()
        
        if not has_id:
            print("Repairing notification_settings: adding id column...")
            # 移除旧主键 (假设是 user_id)
            try:
                await conn.execute(text("ALTER TABLE notification_settings DROP CONSTRAINT IF EXISTS notification_settings_pkeyCASCADE"))
            except Exception as e:
                print(f"Note: Could not drop constraint: {e}")

            # 添加 id 列
            await conn.execute(text("ALTER TABLE notification_settings ADD COLUMN IF NOT EXISTS id SERIAL PRIMARY KEY"))
            print("Added id column as PRIMARY KEY.")
        else:
            print("notification_settings already has an id column.")

        # 2. 检查 created_at 和 updated_at
        for col in ['created_at', 'updated_at']:
            result = await conn.execute(text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = 'notification_settings' AND column_name = '{col}';
            """))
            if not result.fetchone():
                print(f"Adding {col} to notification_settings...")
                await conn.execute(text(f"ALTER TABLE notification_settings ADD COLUMN {col} TIMESTAMP DEFAULT NOW()"))

        print("Database repair completed successfully.")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(repair())
