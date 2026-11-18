"""Read-only truck reporting using the existing phơi financial source of truth."""
from decimal import Decimal

from app.access import phois_query
from app.models import Phoi


METRICS = ('revenue', 'fuel', 'other_expenses', 'wages', 'expenses', 'profit')


def empty_totals():
    return dict(phoi_count=0, **{key: Decimal('0') for key in METRICS})


def build_truck_report(actor, trucks, start_day, end_day, truck_id=None):
    """Attribute the entire confirmed phơi to its departure date, inclusively.

    Fuel retains the model's legacy shared-log allocation, even when another
    attached phơi falls outside the reporting period or is not yet confirmed.
    Soft-deleted trucks remain available for historical reporting.
    """
    truck_rows = {
        truck.id: dict(empty_totals(), truck=truck, label=truck.license_plate)
        for truck in trucks if truck_id is None or truck.id == truck_id
    }
    monthly = {}
    first_month = start_day.year * 12 + start_day.month - 1
    last_month = end_day.year * 12 + end_day.month - 1
    for month_index in range(first_month, last_month + 1):
        year, month = divmod(month_index, 12)
        key = f'{year:04d}-{month + 1:02d}'
        monthly[key] = dict(empty_totals(), label=f'{month + 1:02d}/{year:04d}', month=key)

    query = phois_query(actor).filter(
        Phoi.status == 'confirmed',
        Phoi.departure_date >= start_day,
        Phoi.departure_date <= end_day,
        Phoi.truck_id.in_(truck_rows),
    )
    totals = empty_totals()
    details = {}
    for phoi in query.order_by(Phoi.departure_date, Phoi.id):
        fuel = phoi.fuel_expenses()
        operating_expenses = phoi.total_expenses()
        wages = phoi.driver_wage
        amounts = dict(
            revenue=phoi.total_revenue_full(),
            fuel=fuel,
            other_expenses=operating_expenses - fuel,
            wages=wages,
            expenses=operating_expenses + wages,
            profit=phoi.owner_profit(),
        )
        month = f'{phoi.departure_date.year:04d}-{phoi.departure_date.month:02d}'
        key = (month, phoi.truck_id)
        if key not in details:
            details[key] = dict(empty_totals(), truck=truck_rows[phoi.truck_id]['truck'],
                                month=month, label=monthly[month]['label'])
        for row in (totals, truck_rows[phoi.truck_id], monthly[month], details[key]):
            row['phoi_count'] += 1
            for metric, amount in amounts.items():
                row[metric] += amount

    return dict(
        totals=totals,
        truck_rows=list(truck_rows.values()),
        monthly_rows=list(monthly.values()),
        detail_rows=sorted(details.values(), key=lambda row: (row['month'], row['truck'].license_plate)),
    )
