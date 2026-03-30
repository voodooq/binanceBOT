"""add id and timestamps to notification settings

Revision ID: b3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-02-26 17:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. 移除旧主键
    op.drop_constraint('notification_settings_pkey', 'notification_settings', type_='primary')
    
    # 2. 添加新列 id, created_at, updated_at
    op.add_column('notification_settings', sa.Column('id', sa.Integer(), nullable=True))
    op.add_column('notification_settings', sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True))
    op.add_column('notification_settings', sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True))
    
    # 3. 为现有数据填充 ID
    # 由于 user_id 目前是唯一的，我们可以暂时用它或者是自增序列
    op.execute("CREATE SEQUENCE IF NOT EXISTS notification_settings_id_seq")
    op.execute("UPDATE notification_settings SET id = nextval('notification_settings_id_seq')")
    
    # 4. 设置 id 为非空并设为主键
    op.alter_column('notification_settings', 'id', nullable=False)
    op.create_primary_key('notification_settings_pkey', 'notification_settings', ['id'])
    op.create_index(op.f('ix_notification_settings_id'), 'notification_settings', ['id'], unique=False)
    
    # 5. 为 user_id 添加唯一约束（因为它之前是主键）
    op.create_unique_constraint('uq_notification_settings_user_id', 'notification_settings', ['user_id'])


def downgrade() -> None:
    op.drop_constraint('uq_notification_settings_user_id', 'notification_settings', type_='unique')
    op.drop_index(op.f('ix_notification_settings_id'), table_name='notification_settings')
    op.drop_constraint('notification_settings_pkey', 'notification_settings', type_='primary')
    
    op.drop_column('notification_settings', 'updated_at')
    op.drop_column('notification_settings', 'created_at')
    op.drop_column('notification_settings', 'id')
    
    # 恢复 user_id 作为主键
    op.create_primary_key('notification_settings_pkey', 'notification_settings', ['user_id'])
    op.execute("DROP SEQUENCE IF EXISTS notification_settings_id_seq")
