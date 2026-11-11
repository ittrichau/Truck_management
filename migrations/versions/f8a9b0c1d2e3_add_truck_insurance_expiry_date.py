"""Add an optional insurance expiry date entered directly for each truck.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-11-11
"""
from alembic import op
import sqlalchemy as sa


revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('trucks') as batch_op:
        batch_op.add_column(sa.Column(
            'insurance_expiry_date', sa.Date(), nullable=True,
            comment='Ngày hết hạn bảo hiểm',
        ))


def downgrade():
    # Back up entered insurance dates before dropping this column.
    with op.batch_alter_table('trucks') as batch_op:
        batch_op.drop_column('insurance_expiry_date')
