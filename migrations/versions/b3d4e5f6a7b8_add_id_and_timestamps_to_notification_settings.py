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


def _get_columns(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table_name)}


def _get_pk(inspector: sa.Inspector, table_name: str) -> tuple[str | None, list[str]]:
    pk = inspector.get_pk_constraint(table_name) or {}
    return pk.get("name"), list(pk.get("constrained_columns") or [])


def _has_unique_on_columns(
    inspector: sa.Inspector, table_name: str, target_columns: list[str]
) -> bool:
    for constraint in inspector.get_unique_constraints(table_name):
        if list(constraint.get("column_names") or []) == target_columns:
            return True
    return False


def _has_index(inspector: sa.Inspector, table_name: str, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    table_name = "notification_settings"
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    columns = _get_columns(inspector, table_name)
    pk_name, pk_columns = _get_pk(inspector, table_name)

    # 如果旧主键仍然在 user_id 上，先移除
    if pk_columns == ["user_id"]:
        op.drop_constraint(pk_name or "notification_settings_pkey", table_name, type_="primary")

    # 确保序列存在
    op.execute("CREATE SEQUENCE IF NOT EXISTS notification_settings_id_seq")

    # 添加 id 列（若缺失）
    if "id" not in columns:
        op.add_column(table_name, sa.Column("id", sa.Integer(), nullable=True))

    # 确保 id 列使用序列作为默认值，并为已有数据补值
    op.execute(
        "ALTER TABLE notification_settings "
        "ALTER COLUMN id SET DEFAULT nextval('notification_settings_id_seq')"
    )
    op.execute(
        "UPDATE notification_settings "
        "SET id = nextval('notification_settings_id_seq') "
        "WHERE id IS NULL"
    )
    op.execute(
        "SELECT setval("
        "'notification_settings_id_seq', "
        "COALESCE((SELECT MAX(id) FROM notification_settings), 1), "
        "true)"
    )

    # 添加 created_at / updated_at（若缺失）
    if "created_at" not in columns:
        op.add_column(
            table_name,
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        )
    if "updated_at" not in columns:
        op.add_column(
            table_name,
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        )

    # 为历史数据补时间戳
    op.execute("UPDATE notification_settings SET created_at = NOW() WHERE created_at IS NULL")
    op.execute("UPDATE notification_settings SET updated_at = NOW() WHERE updated_at IS NULL")

    # 确保 id 非空
    op.alter_column(table_name, "id", existing_type=sa.Integer(), nullable=False)

    # 重新读取表结构，确保主键在 id 上
    inspector = sa.inspect(bind)
    pk_name, pk_columns = _get_pk(inspector, table_name)
    if pk_columns != ["id"]:
        if pk_name:
            op.drop_constraint(pk_name, table_name, type_="primary")
        op.create_primary_key("notification_settings_pkey", table_name, ["id"])

    # 为 id 创建索引（若缺失）
    inspector = sa.inspect(bind)
    id_index_name = op.f("ix_notification_settings_id")
    if not _has_index(inspector, table_name, id_index_name):
        op.create_index(id_index_name, table_name, ["id"], unique=False)

    # user_id 在新模型中应保持唯一
    inspector = sa.inspect(bind)
    if not _has_unique_on_columns(inspector, table_name, ["user_id"]):
        op.create_unique_constraint(
            "uq_notification_settings_user_id",
            table_name,
            ["user_id"],
        )


def downgrade() -> None:
    table_name = "notification_settings"
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for constraint in inspector.get_unique_constraints(table_name):
        if list(constraint.get("column_names") or []) == ["user_id"]:
            op.drop_constraint(constraint["name"], table_name, type_="unique")
            break

    inspector = sa.inspect(bind)
    id_index_name = op.f("ix_notification_settings_id")
    if _has_index(inspector, table_name, id_index_name):
        op.drop_index(id_index_name, table_name=table_name)

    inspector = sa.inspect(bind)
    pk_name, pk_columns = _get_pk(inspector, table_name)
    if pk_columns == ["id"] and pk_name:
        op.drop_constraint(pk_name, table_name, type_="primary")

    inspector = sa.inspect(bind)
    columns = _get_columns(inspector, table_name)
    if "updated_at" in columns:
        op.drop_column(table_name, "updated_at")
    if "created_at" in columns:
        op.drop_column(table_name, "created_at")
    if "id" in columns:
        op.drop_column(table_name, "id")

    inspector = sa.inspect(bind)
    _, pk_columns = _get_pk(inspector, table_name)
    if pk_columns != ["user_id"]:
        op.create_primary_key("notification_settings_pkey", table_name, ["user_id"])

    op.execute("DROP SEQUENCE IF EXISTS notification_settings_id_seq")