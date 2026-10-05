"""Add weigh-ticket evidence for return trips.

Revision ID: aa1b2c3d4e5f
Revises: d4e5f6a7b8c9
Create Date: 2026-10-05
"""

from alembic import op
import sqlalchemy as sa


revision = 'aa1b2c3d4e5f'
down_revision = 'd4e5f6a7b8c9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.add_column(sa.Column('weigh_ticket_number', sa.String(length=100), nullable=True))

    with op.batch_alter_table('phoi_attachments') as batch_op:
        batch_op.add_column(sa.Column('return_trip_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_phoi_attachments_return_trip_id', ['return_trip_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_phoi_attachments_return_trip_id_phoi_return_trips',
            'phoi_return_trips',
            ['return_trip_id'],
            ['id'],
            ondelete='CASCADE',
        )


def downgrade():
    with op.batch_alter_table('phoi_attachments') as batch_op:
        batch_op.drop_constraint(
            'fk_phoi_attachments_return_trip_id_phoi_return_trips', type_='foreignkey'
        )
        batch_op.drop_index('ix_phoi_attachments_return_trip_id')
        batch_op.drop_column('return_trip_id')

    with op.batch_alter_table('phoi_return_trips') as batch_op:
        batch_op.drop_column('weigh_ticket_number')
