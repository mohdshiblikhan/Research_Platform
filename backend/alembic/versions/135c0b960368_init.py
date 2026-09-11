"""init

Revision ID: 135c0b960368
Revises: efe04964a4dc
Create Date: 2026-08-25 00:24:47.182534

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '135c0b960368'
down_revision: Union[str, Sequence[str], None] = 'efe04964a4dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
