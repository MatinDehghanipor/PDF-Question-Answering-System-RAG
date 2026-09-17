"""make feedback.rating nullable

Phase 9 (FR-31): the rating and the comment are two *independently* optional
signals — UC9 reads "User optionally rates the answer (positive/negative)
and/or adds a comment".  The Phase-0 schema created ``feedback.rating`` as
NOT NULL, which made a comment-only submission impossible, so this migration
relaxes that one column.  No data is altered or dropped: existing rows keep
their rating values.

Revision ID: d4e2a1b8c9f0
Revises: c3f1f5f4d7ab
Create Date: 2026-09-14 21:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e2a1b8c9f0'
down_revision: Union[str, None] = 'c3f1f5f4d7ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Apply this migration.

    ``existing_type`` is required so Alembic knows what it is altering, and
    ``batch_alter_table`` (combined with ``render_as_batch`` in env.py) lets
    SQLite — which cannot ALTER COLUMN in place — recreate the table instead.
    """
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.alter_column(
            'rating',
            existing_type=sa.Enum('positive', 'negative', name='feedbackrating'),
            nullable=True,
        )


def downgrade() -> None:
    """Revert this migration.

    Note: this fails loudly on any comment-only row (``rating IS NULL``), which
    is the correct behaviour — silently deleting a user's comment to restore
    the old constraint would lose data.
    """
    with op.batch_alter_table('feedback', schema=None) as batch_op:
        batch_op.alter_column(
            'rating',
            existing_type=sa.Enum('positive', 'negative', name='feedbackrating'),
            nullable=False,
        )
