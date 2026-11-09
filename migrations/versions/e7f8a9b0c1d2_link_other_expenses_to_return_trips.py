"""Link other expenses to their return trip; retain legacy outbound expenses.

Revision ID: e7f8a9b0c1d2
Revises: d5e6f7a8b9c0
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'e7f8a9b0c1d2'
down_revision = 'd5e6f7a8b9c0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi_expenses') as batch_op:
        batch_op.add_column(sa.Column('return_trip_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_phoi_expenses_return_trip_id', 'phoi_return_trips',
            ['return_trip_id'], ['id'], ondelete='CASCADE',
        )
        batch_op.create_index('ix_phoi_expenses_return_trip_id', ['return_trip_id'])


def downgrade():
    expenses = sa.table('phoi_expenses', sa.column('return_trip_id', sa.Integer()))
    if op.get_bind().execute(
        sa.select(expenses.c.return_trip_id)
        .where(expenses.c.return_trip_id.isnot(None)).limit(1)
    ).first():
        raise RuntimeError(
            'Cannot downgrade: return-trip expenses would lose their trip association. '
            'Back up and explicitly resolve these expenses first.'
        )
    with op.batch_alter_table('phoi_expenses') as batch_op:
        batch_op.drop_index('ix_phoi_expenses_return_trip_id')
        batch_op.drop_constraint('fk_phoi_expenses_return_trip_id', type_='foreignkey')
        batch_op.drop_column('return_trip_id')
