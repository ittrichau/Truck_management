"""change fuel_price effective_from_to to datetime

Revision ID: 3e2cc001308f
Revises: fbedc3563d13
Create Date: 2026-06-22 16:30:53.756953

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3e2cc001308f'
down_revision = 'fbedc3563d13'
branch_labels = None
depends_on = None


def upgrade():
    # Chỉ thay đổi kiểu dữ liệu của fuel_prices (Date -> DateTime)
    # fuel_logs.phoi_id đã được xóa ở migration trước
    with op.batch_alter_table('fuel_prices', schema=None) as batch_op:
        batch_op.alter_column('effective_from',
               existing_type=sa.DATE(),
               type_=sa.DateTime(),
               existing_nullable=False)
        batch_op.alter_column('effective_to',
               existing_type=sa.DATE(),
               type_=sa.DateTime(),
               existing_nullable=True)


def downgrade():
    with op.batch_alter_table('fuel_prices', schema=None) as batch_op:
        batch_op.alter_column('effective_to',
               existing_type=sa.DateTime(),
               type_=sa.DATE(),
               existing_nullable=True)
        batch_op.alter_column('effective_from',
               existing_type=sa.DateTime(),
               type_=sa.DATE(),
               existing_nullable=False)