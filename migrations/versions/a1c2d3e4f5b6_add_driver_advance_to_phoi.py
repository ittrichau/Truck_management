"""Record money advanced by the manager to the driver for the whole phơi.

Revision ID: a1c2d3e4f5b6
Revises: f8a9b0c1d2e3
Create Date: 2026-11-17
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c2d3e4f5b6'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(sa.Column(
            'driver_advance', sa.Numeric(precision=12, scale=2),
            nullable=False, server_default='0',
            comment='Tiền quản lý/chủ xe đã ứng trước cho tài xế',
        ))


def downgrade():
    # Export recorded advances before dropping this column and reverting the app.
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_column('driver_advance')
