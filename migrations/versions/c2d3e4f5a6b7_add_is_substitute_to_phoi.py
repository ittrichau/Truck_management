"""Add substitute mode to phoi

Revision ID: c2d3e4f5a6b7
Revises: b1e2c3d4f5a6
Create Date: 2026-09-24

"""
from alembic import op
import sqlalchemy as sa


revision = 'c2d3e4f5a6b7'
down_revision = 'b1e2c3d4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(
            sa.Column(
                'is_substitute',
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
                comment='Chuyến chạy giùm, dùng cặp xe-tài xế khác với gán mặc định'
            )
        )


def downgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_column('is_substitute')
