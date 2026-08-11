"""add composite index on chat_messages (session_id, created_at)

Revision ID: 11060ac24ae6
Revises: 06f20a30109b
Create Date: 2026-08-11 18:48:04.936969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '11060ac24ae6'
down_revision: Union[str, None] = '06f20a30109b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级迁移：添加 (session_id, created_at) 复合索引"""
    op.create_index(
        "ix_chat_messages_session_created",
        "chat_messages",
        ["session_id", "created_at"],
    )


def downgrade() -> None:
    """回滚迁移：删除复合索引"""
    op.drop_index("ix_chat_messages_session_created", table_name="chat_messages")
