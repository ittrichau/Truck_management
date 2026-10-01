"""Merge payment and fuel migration heads.

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2, a8b9c0d1e2f3
Create Date: 2026-10-01

This merge revision intentionally performs no schema changes. It reunites
independent migration branches so `flask db upgrade` has one head.
"""

revision = "c9d0e1f2a3b4"
down_revision = ("b7c8d9e0f1a2", "a8b9c0d1e2f3")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
