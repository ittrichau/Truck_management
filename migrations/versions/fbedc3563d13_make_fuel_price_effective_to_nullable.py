"""Make fuel_price effective_to nullable

Revision ID: fbedc3563d13
Revises: 09e0d1bd9d4f
Create Date: 2026-06-11 14:27:46.890527

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'fbedc3563d13'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Chỉ áp dụng thay đổi cột effective_to thành nullable
    with op.batch_alter_table('fuel_prices', schema=None) as batch_op:
        batch_op.alter_column('effective_to',
               existing_type=sa.DATE(),
               nullable=True)


def downgrade():
    with op.batch_alter_table('fuel_prices', schema=None) as batch_op:
        batch_op.alter_column('effective_to',
               existing_type=sa.DATE(),
               nullable=False)
