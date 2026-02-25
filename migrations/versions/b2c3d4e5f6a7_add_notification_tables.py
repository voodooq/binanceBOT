"""Add notification tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-25 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """创建通知流水表和用户通知偏好设置表。"""
    # NOTE: 使用原生 SQL 创建枚举，IF NOT EXISTS 保证幂等
    # 避免 SQLAlchemy sa.Enum 在 create_table 时重复创建枚举
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'notification_level_enum') THEN
                CREATE TYPE notification_level_enum AS ENUM ('info', 'success', 'warning', 'error', 'critical');
            END IF;
        END
        $$;
    """)

    op.create_table('notifications',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('level', sa.Text(), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('message', sa.String(length=2000), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_id'), 'notifications', ['id'], unique=False)

    # 将 level 列的类型改为枚举（Text -> notification_level_enum）
    op.execute("ALTER TABLE notifications ALTER COLUMN level TYPE notification_level_enum USING level::notification_level_enum")

    op.create_table('notification_settings',
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('telegram_enabled', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('email_enabled', sa.Boolean(), nullable=True, server_default='false'),
        sa.Column('web_enabled', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('min_level', sa.Text(), nullable=True),
        sa.Column('telegram_chat_id', sa.String(length=100), nullable=True),
        sa.Column('email_address', sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint('user_id')
    )

    # 将 min_level 列的类型改为枚举
    op.execute("ALTER TABLE notification_settings ALTER COLUMN min_level TYPE notification_level_enum USING min_level::notification_level_enum")


def downgrade() -> None:
    """移除通知相关表。"""
    op.drop_table('notification_settings')
    op.drop_index(op.f('ix_notifications_id'), table_name='notifications')
    op.drop_table('notifications')
    op.execute("DROP TYPE IF EXISTS notification_level_enum")
