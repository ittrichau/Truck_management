"""Add up to two additional customers to each existing trip, without rewriting legacy data.

Revision ID: f1a2b3c4d5e6
Revises: d8e9f0a1b2c3
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'phoi_cargo_items',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('phoi_id', sa.Integer(), sa.ForeignKey('phoi.id', ondelete='CASCADE'), nullable=False),
        sa.Column('return_trip_id', sa.Integer(), sa.ForeignKey('phoi_return_trips.id', ondelete='CASCADE')),
        sa.Column('item_order', sa.Integer(), nullable=False),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), nullable=False),
        sa.Column('cargo_description', sa.String(300), nullable=False),
        sa.Column('cargo_weight_tons', sa.Numeric(10, 3)),
        sa.Column('payment_method', sa.String(20), nullable=False),
        sa.Column('price_per_ton', sa.Numeric(12, 2)),
        sa.Column('revenue_full', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('revenue_collected', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('manager_revenue_collected', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.CheckConstraint('item_order BETWEEN 2 AND 3', name='ck_cargo_item_order'),
        sa.CheckConstraint("payment_method IN ('fixed', 'per_ton')", name='ck_cargo_payment_method'),
        sa.CheckConstraint('revenue_full >= 0 AND revenue_collected >= 0 AND manager_revenue_collected >= 0', name='ck_cargo_nonnegative'),
    )
    for field in ('phoi_id', 'return_trip_id', 'customer_id'):
        op.create_index(f'ix_phoi_cargo_items_{field}', 'phoi_cargo_items', [field])


def downgrade():
    # An old application cannot represent shared customers. Never silently discard their debts.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM phoi_cargo_items')).scalar():
        raise RuntimeError('Không thể hạ phiên bản khi còn hàng ghép. Hãy sao lưu và đối soát dữ liệu trước.')
    op.drop_table('phoi_cargo_items')
