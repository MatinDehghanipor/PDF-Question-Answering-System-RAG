"""add source_document_ids to answers table

Revision ID: c3f1f5f4d7ab
Revises: 24275d24704b
Create Date: 2026-09-14 20:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f1f5f4d7ab'
down_revision: Union[str, None] = '24275d24704b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration."""
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_document_ids', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Revert this migration."""
    with op.batch_alter_table('answers', schema=None) as batch_op:
        batch_op.drop_column('source_document_ids')
