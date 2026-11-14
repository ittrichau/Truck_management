"""Manager ownership and customer sharing; legacy rows stay admin-only.

Revision ID: a1c2e3f4b5d6
Revises: f8a9b0c1d2e3
"""
from alembic import op
import sqlalchemy as sa

revision = 'a1c2e3f4b5d6'
down_revision = 'f8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    for table in ('users', 'trucks'):
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column('manager_id', sa.Integer(), nullable=True))
            batch.create_foreign_key(f'fk_{table}_manager_id', 'users', ['manager_id'], ['id'])
            batch.create_index(f'ix_{table}_manager_id', ['manager_id'])
    op.create_table('manager_customers',
        sa.Column('manager_id', sa.Integer(), sa.ForeignKey('users.id'), primary_key=True),
        sa.Column('customer_id', sa.Integer(), sa.ForeignKey('customers.id'), primary_key=True))
    with op.batch_alter_table('activity_logs') as batch:
        for column, target in (('scope_truck_id', 'trucks'), ('scope_manager_id', 'users')):
            batch.add_column(sa.Column(column, sa.Integer(), nullable=True))
            batch.create_foreign_key(f'fk_activity_logs_{column}', target, [column], ['id'])
            batch.create_index(f'ix_activity_logs_{column}', [column])


def downgrade():
    # Export assignments before downgrade; financial records are never rewritten.
    with op.batch_alter_table('activity_logs') as batch:
        for column in ('scope_manager_id', 'scope_truck_id'):
            batch.drop_index(f'ix_activity_logs_{column}')
            batch.drop_constraint(f'fk_activity_logs_{column}', type_='foreignkey')
            batch.drop_column(column)
    op.drop_table('manager_customers')
    for table in ('trucks', 'users'):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f'ix_{table}_manager_id')
            batch.drop_constraint(f'fk_{table}_manager_id', type_='foreignkey')
            batch.drop_column('manager_id')
