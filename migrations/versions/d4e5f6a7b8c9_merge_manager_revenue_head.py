"""Merge manager-revenue migration head.

Revision ID: d4e5f6a7b8c9
Revises: c9d0e1f2a3b4, c6d7e8f9a0b1
Create Date: 2026-10-01

This merge revision intentionally performs no schema changes. It reunites the
payment/fuel and manager-revenue migration branches so deployments have one
unambiguous Alembic head.
"""

revision = "d4e5f6a7b8c9"
down_revision = ("c9d0e1f2a3b4", "c6d7e8f9a0b1")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
