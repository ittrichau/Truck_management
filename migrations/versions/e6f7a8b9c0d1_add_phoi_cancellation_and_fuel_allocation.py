"""Add phoi cancellation and fuel allocation tracking

Revision ID: e6f7a8b9c0d1
Revises: b2c3d4e5f6a7
Create Date: 2026-10-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'e6f7a8b9c0d1'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(sa.Column('cancelled_by_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('cancelled_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('cancellation_reason', sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            'fk_phoi_cancelled_by_id_users', 'users', ['cancelled_by_id'], ['id']
        )
        batch_op.create_index('ix_phoi_cancelled_by_id', ['cancelled_by_id'])

    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.add_column(
            sa.Column(
                'allocation_status',
                sa.String(length=20),
                nullable=False,
                server_default='allocated',
            )
        )
        batch_op.add_column(
            sa.Column('unallocated_from_cancelled_phoi_id', sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            'fk_fuel_logs_unallocated_from_cancelled_phoi_id_phoi',
            'phoi',
            ['unallocated_from_cancelled_phoi_id'],
            ['id'],
        )
        batch_op.create_index('ix_fuel_logs_allocation_status', ['allocation_status'])
        batch_op.create_index(
            'ix_fuel_logs_unallocated_from_cancelled_phoi_id',
            ['unallocated_from_cancelled_phoi_id'],
        )


def downgrade():
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.drop_index('ix_fuel_logs_unallocated_from_cancelled_phoi_id')
        batch_op.drop_index('ix_fuel_logs_allocation_status')
        batch_op.drop_constraint(
            'fk_fuel_logs_unallocated_from_cancelled_phoi_id_phoi', type_='foreignkey'
        )
        batch_op.drop_column('unallocated_from_cancelled_phoi_id')
        batch_op.drop_column('allocation_status')

    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_index('ix_phoi_cancelled_by_id')
        batch_op.drop_constraint('fk_phoi_cancelled_by_id_users', type_='foreignkey')
        batch_op.drop_column('cancellation_reason')
        batch_op.drop_column('cancelled_at')
        batch_op.drop_column('cancelled_by_id')
