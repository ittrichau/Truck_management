"""Direct inspection/permit expiry dates; preserve legacy computed expiries.

Revision ID: c7e8f901a2b3
Revises: b8d2c4f6a091
"""
from calendar import monthrange
from datetime import date

from alembic import op
import sqlalchemy as sa

revision = 'c7e8f901a2b3'
down_revision = 'b8d2c4f6a091'
branch_labels = None
depends_on = None


def legacy_expiry(start, months):
    # Exactly the old model's behavior, including null/zero terms and month ends.
    if not start or not months:
        return None
    month = start.month + months
    year = start.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def trucks_table(include_new=False):
    columns = [sa.column('id', sa.Integer()), sa.column('inspection_date', sa.Date()),
               sa.column('inspection_expiry_months', sa.Integer()), sa.column('permit_date', sa.Date()),
               sa.column('permit_expiry_months', sa.Integer())]
    if include_new:
        columns += [sa.column('inspection_expires_on', sa.Date()), sa.column('permit_expires_on', sa.Date())]
    return sa.table('trucks', *columns)


def upgrade():
    connection = op.get_bind()
    # Validate every old date before changing the schema; never guess bad dates.
    planned = []
    for row in connection.execute(sa.select(trucks_table())).mappings():
        try:
            planned.append((row['id'], legacy_expiry(row['inspection_date'], row['inspection_expiry_months']),
                            legacy_expiry(row['permit_date'], row['permit_expiry_months'])))
        except (ValueError, OverflowError) as exc:
            raise RuntimeError(f'Cannot migrate expiry for truck #{row["id"]}; correct legacy dates/terms first.') from exc
    with op.batch_alter_table('trucks') as batch:
        batch.add_column(sa.Column('inspection_expires_on', sa.Date(), nullable=True,
                                   comment='Ngày hết hạn đăng kiểm nhập trực tiếp'))
        batch.add_column(sa.Column('permit_expires_on', sa.Date(), nullable=True,
                                   comment='Ngày hết hạn phù hiệu nhập trực tiếp'))
    trucks = trucks_table(include_new=True)
    for identity, inspection, permit in planned:
        connection.execute(trucks.update().where(trucks.c.id == identity).values(
            inspection_expires_on=inspection, permit_expires_on=permit))


def downgrade():
    # New/edited/cleared direct dates cannot be represented by the retained legacy
    # data safely. Block rather than silently discarding dates or restoring blanks.
    for row in op.get_bind().execute(sa.select(trucks_table(include_new=True))).mappings():
        if (row['inspection_expires_on'] != legacy_expiry(row['inspection_date'], row['inspection_expiry_months'])
                or row['permit_expires_on'] != legacy_expiry(row['permit_date'], row['permit_expiry_months'])):
            raise RuntimeError('Cannot downgrade: direct expiry dates would be lost or changed. Back up and explicitly reconcile truck dates first.')
    with op.batch_alter_table('trucks') as batch:
        batch.drop_column('permit_expires_on')
        batch.drop_column('inspection_expires_on')
