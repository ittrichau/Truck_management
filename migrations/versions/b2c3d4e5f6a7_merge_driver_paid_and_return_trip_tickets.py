"""Merge driver-paid and return-trip weigh-ticket migration heads.

Revision ID: b2c3d4e5f6a7
Revises: 975a0bd04827, aa1b2c3d4e5f
Create Date: 2026-10-06

This merge revision intentionally performs no schema or data changes. It reunites
parallel migrations so Alembic has one deterministic deployment head.
"""

revision = "b2c3d4e5f6a7"
down_revision = ("975a0bd04827", "aa1b2c3d4e5f")
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
