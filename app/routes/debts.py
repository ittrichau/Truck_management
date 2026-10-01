from collections import defaultdict
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.models import Phoi

bp = Blueprint('debts', __name__)


@bp.route('/debts')
@login_required
def index():
    """Báo cáo công nợ chủ hàng từ các phơi đã xác nhận."""
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập trang công nợ.', 'danger')
        return redirect(url_for('phoi.index'))

    phois = (
        Phoi.query.filter_by(status='confirmed')
        .options(selectinload(Phoi.return_trips))
        .order_by(Phoi.departure_date.desc(), Phoi.id.desc())
        .all()
    )

    customer_debts = defaultdict(
        lambda: {
            'customer': None,
            'revenue_full': Decimal('0'),
            'revenue_collected': Decimal('0'),
            'trip_count': 0,
        }
    )

    def add_debt(customer, revenue_full, revenue_collected):
        if not customer:
            return
        debt = customer_debts[customer.id]
        debt['customer'] = customer
        debt['revenue_full'] += revenue_full or Decimal('0')
        debt['revenue_collected'] += revenue_collected or Decimal('0')
        debt['trip_count'] += 1

    for phoi in phois:
        add_debt(phoi.customer, phoi.revenue_full, phoi.revenue_collected)
        for return_trip in phoi.return_trips:
            add_debt(
                return_trip.customer,
                return_trip.revenue_full,
                return_trip.revenue_collected,
            )

    debts = []
    for debt in customer_debts.values():
        debt['outstanding'] = debt['revenue_full'] - debt['revenue_collected']
        debts.append(debt)
    debts.sort(key=lambda debt: (-debt['outstanding'], debt['customer'].name.lower()))

    totals = {
        'revenue_full': sum((debt['revenue_full'] for debt in debts), Decimal('0')),
        'revenue_collected': sum((debt['revenue_collected'] for debt in debts), Decimal('0')),
        'outstanding': sum((debt['outstanding'] for debt in debts), Decimal('0')),
    }
    return render_template('debts/index.html', debts=debts, totals=totals)
