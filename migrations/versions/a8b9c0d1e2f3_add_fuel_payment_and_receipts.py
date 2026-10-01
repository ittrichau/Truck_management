"""Add fuel payer and receipt uploads

Revision ID: a8b9c0d1e2f3
Revises: f5a6b7c8d9e0
Create Date: 2026-10-01

"""
from alembic import op
import sqlalchemy as sa

revision = 'a8b9c0d1e2f3'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.add_column(
            sa.Column('paid_by', sa.String(length=20), nullable=False, server_default='owner')
        )

    op.create_table(
        'fuel_receipts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fuel_log_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False, server_default='image/jpeg'),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['fuel_log_id'], ['fuel_logs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('storage_key'),
    )
    op.create_index('ix_fuel_receipts_fuel_log_id', 'fuel_receipts', ['fuel_log_id'])


def downgrade():
    op.drop_index('ix_fuel_receipts_fuel_log_id', table_name='fuel_receipts')
    op.drop_table('fuel_receipts')
    with op.batch_alter_table('fuel_logs') as batch_op:
        batch_op.drop_column('paid_by')
