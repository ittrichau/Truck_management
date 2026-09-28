"""Add phoi attachments and cargo weight fields

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-09-25

"""
from alembic import op
import sqlalchemy as sa

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.add_column(sa.Column('cargo_weight_tons', sa.Numeric(precision=10, scale=3), nullable=True))
        batch_op.add_column(sa.Column('weigh_ticket_number', sa.String(length=100), nullable=True))

    op.create_table(
        'phoi_attachments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('phoi_id', sa.Integer(), nullable=False),
        sa.Column('attachment_type', sa.String(length=30), nullable=False),
        sa.Column('original_filename', sa.String(length=255), nullable=False),
        sa.Column('storage_key', sa.String(length=500), nullable=False),
        sa.Column('mime_type', sa.String(length=100), nullable=False, server_default='image/jpeg'),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('notes', sa.String(length=500), nullable=True),
        sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['phoi_id'], ['phoi.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('storage_key'),
    )
    op.create_index('ix_phoi_attachments_phoi_id', 'phoi_attachments', ['phoi_id'])
    op.create_index('ix_phoi_attachments_attachment_type', 'phoi_attachments', ['attachment_type'])


def downgrade():
    op.drop_index('ix_phoi_attachments_attachment_type', table_name='phoi_attachments')
    op.drop_index('ix_phoi_attachments_phoi_id', table_name='phoi_attachments')
    op.drop_table('phoi_attachments')
    with op.batch_alter_table('phoi') as batch_op:
        batch_op.drop_column('weigh_ticket_number')
        batch_op.drop_column('cargo_weight_tons')
