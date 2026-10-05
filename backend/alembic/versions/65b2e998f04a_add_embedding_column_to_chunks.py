"""add embedding column to chunks

Revision ID: 65b2e998f04a
Revises: 8991abfba909
Create Date: 2026-10-06 02:58:45.407665

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '65b2e998f04a'
down_revision: Union[str, Sequence[str], None] = '8991abfba909'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

from pgvector.sqlalchemy import Vector

def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("chunks", sa.Column("embedding", Vector(384), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chunks", "embedding")
