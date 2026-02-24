"""Add exchange column to api_keys

Revision ID: a1b2c3d4e5f6
Revises: 4bbba8b81c22
Create Date: 2026-02-24 12:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '4bbba8b81c22'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add exchange column with default value 'binance'."""
    op.add_column('api_keys', sa.Column('exchange', sa.String(length=50), nullable=False, server_default='binance'))


def downgrade() -> None:
    """Remove exchange column."""
    op.drop_column('api_keys', 'exchange')
