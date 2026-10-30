"""Add fuel station classification and proof image type

Revision ID: b3c4d5e6f7a8
Revises: a8b9c0d1e2f3
Create Date: 2026-10-30

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3c4d5e6f7a8'
down_revision = 'a8b9c0d1e2f3'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.add_column(
            sa.Column('is_home_station', sa.Boolean(), nullable=False, server_default=sa.false())
        )

    with op.batch_alter_table('fuel_receipts') as batch_op:
        batch_op.add_column(
            sa.Column('image_type', sa.String(length=20), nullable=False, server_default='receipt')
        )


def downgrade():
    with op.batch_alter_table('fuel_receipts') as batch_op:
        batch_op.drop_column('image_type')

    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.drop_column('is_home_station')