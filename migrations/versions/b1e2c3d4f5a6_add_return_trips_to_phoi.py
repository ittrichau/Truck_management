"""Add return trips to phoi

Revision ID: b1e2c3d4f5a6
Revises: 790cbc2d2c08
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1e2c3d4f5a6'
down_revision = '790cbc2d2c08'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'phoi_return_trips',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phoi_id', sa.Integer(), nullable=False),
        sa.Column('trip_order', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('return_date', sa.Date(), nullable=True),
        sa.Column('origin', sa.String(length=200), nullable=False),
        sa.Column('destination', sa.String(length=200), nullable=False),
        sa.Column('cargo_description', sa.String(length=300), nullable=True),
        sa.Column('km_start', sa.Integer(), nullable=True),
        sa.Column('km_end', sa.Integer(), nullable=True),
        sa.Column('km_total', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('revenue_full', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('revenue_collected', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['phoi_id'], ['phoi.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_phoi_return_trips_phoi_id', 'phoi_return_trips', ['phoi_id'])


def downgrade():
    op.drop_index('ix_phoi_return_trips_phoi_id', table_name='phoi_return_trips')
    op.drop_table('phoi_return_trips')
