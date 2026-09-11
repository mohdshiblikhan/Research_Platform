"""init

Revision ID: efe04964a4dc
Revises: 517691da3289
Create Date: 2026-08-25 00:15:51.172483

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'efe04964a4dc'
down_revision: Union[str, Sequence[str], None] = '517691da3289'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
