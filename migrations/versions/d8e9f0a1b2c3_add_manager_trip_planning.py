"""Private manager schedules and reconciliation history.

Revision ID: d8e9f0a1b2c3
Revises: c7e8f901a2b3
"""
from alembic import op
import sqlalchemy as sa

revision = 'd8e9f0a1b2c3'
down_revision = 'c7e8f901a2b3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'trip_plans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('manager_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('truck_id', sa.Integer(), sa.ForeignKey('trucks.id'), nullable=False),
        sa.Column('driver_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id')),
        sa.Column('departure_date', sa.Date(), nullable=False),
        sa.Column('return_date', sa.Date()),
        sa.Column('origin', sa.String(200), nullable=False),
        sa.Column('destination', sa.String(200), nullable=False),
        sa.Column('cargo_description', sa.String(300)),
        sa.Column('return_load_status', sa.String(20), nullable=False),
        sa.Column('return_trips', sa.JSON(), nullable=False),
        sa.Column('notes', sa.Text()),
        sa.Column('is_cancelled', sa.Boolean(), nullable=False),
        sa.Column('phoi_id', sa.Integer(), sa.ForeignKey('phoi.id'), unique=True),
        sa.Column('original_data', sa.JSON(), nullable=False),
        sa.Column('actual_data', sa.JSON()),
        sa.Column('reviewed_signature', sa.String(64)),
        sa.Column('synced_at', sa.DateTime()),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.CheckConstraint('return_date IS NULL OR return_date >= departure_date', name='ck_trip_plan_dates'),
        sa.CheckConstraint("return_load_status IN ('unknown', 'loaded', 'empty')", name='ck_trip_plan_return_load'),
    )
    for name in ('manager_id', 'truck_id', 'departure_date'):
        op.create_index('ix_trip_plans_' + name, 'trip_plans', [name])
    op.create_table(
        'trip_plan_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('plan_id', sa.Integer(), sa.ForeignKey('trip_plans.id'), nullable=False),
        sa.Column('actor_id', sa.Integer(), sa.ForeignKey('users.id')),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('before_data', sa.JSON()),
        sa.Column('after_data', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_trip_plan_history_plan_id', 'trip_plan_history', ['plan_id'])


def downgrade():
    # Never silently discard a manager's saved plans or audit trail.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM trip_plans')).scalar():
        raise RuntimeError('Cannot downgrade: export trip plans/history and explicitly remove planning data first.')
    op.drop_table('trip_plan_history')
    op.drop_table('trip_plans')
