"""Add repair expense details and receipt links

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi_expenses') as batch_op:
        batch_op.add_column(
            sa.Column('is_home_repair', sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column('repair_location', sa.String(length=200), nullable=True))

    with op.batch_alter_table('phoi_attachments') as batch_op:
        batch_op.add_column(sa.Column('expense_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_phoi_attachments_expense_id_phoi_expenses',
            'phoi_expenses',
            ['expense_id'],
            ['id'],
            ondelete='CASCADE'
        )
        batch_op.create_index('ix_phoi_attachments_expense_id', ['expense_id'])


def downgrade():
    with op.batch_alter_table('phoi_attachments') as batch_op:
        batch_op.drop_index('ix_phoi_attachments_expense_id')
        batch_op.drop_constraint('fk_phoi_attachments_expense_id_phoi_expenses', type_='foreignkey')
        batch_op.drop_column('expense_id')

    with op.batch_alter_table('phoi_expenses') as batch_op:
        batch_op.drop_column('repair_location')
        batch_op.drop_column('is_home_repair')
