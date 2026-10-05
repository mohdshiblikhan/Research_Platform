"""add search_vector column to chunks

Revision ID: 8991abfba909
Revises: 0293355754ef
Create Date: 2026-10-05 03:52:10.506297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8991abfba909'
down_revision: Union[str, Sequence[str], None] = '0293355754ef'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add search_vector generated column and GIN index to chunks table.

    The column is GENERATED ALWAYS AS STORED — PostgreSQL automatically
    keeps it in sync with the `content` column on every insert or update.
    No application code is needed to maintain it.

    We use op.execute() for the ADD COLUMN step because Alembic's
    add_column() does not support the GENERATED ALWAYS AS syntax.
    The GIN index is created via op.create_index() using the standard
    postgresql_using parameter.
    """
    op.execute("""
        ALTER TABLE chunks
        ADD COLUMN search_vector tsvector
            GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
    """)
    op.create_index(
        "ix_chunks_search_vector",
        "chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove search_vector column and its GIN index."""
    op.drop_index("ix_chunks_search_vector", table_name="chunks")
    op.execute("ALTER TABLE chunks DROP COLUMN search_vector")
