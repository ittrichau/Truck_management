from collections import defaultdict
from decimal import Decimal, InvalidOperation

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Customer, Phoi, PhoiReturnTrip

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

    def add_debt(customer, revenue_full, driver_collected, manager_collected):
        if not customer:
            return
        debt = customer_debts[customer.id]
        debt['customer'] = customer
        debt['revenue_full'] += revenue_full or Decimal('0')
        debt['revenue_collected'] += (
            (driver_collected or Decimal('0')) + (manager_collected or Decimal('0'))
        )
        debt['trip_count'] += 1

    for phoi in phois:
        add_debt(
            phoi.customer,
            phoi.revenue_full,
            phoi.revenue_collected,
            phoi.manager_revenue_collected,
        )
        for return_trip in phoi.return_trips:
            add_debt(
                return_trip.customer,
                return_trip.revenue_full,
                return_trip.revenue_collected,
                return_trip.manager_revenue_collected,
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


@bp.route('/debts/customer/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    """Chi tiết công nợ của một khách hàng — danh sách phơi còn nợ."""
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập trang công nợ.', 'danger')
        return redirect(url_for('phoi.index'))

    customer = Customer.query.get_or_404(customer_id)
    show_all = request.args.get('all') == '1'

    # --- Thu thập tất cả các "dòng nợ" (phơi chính + chuyến về) của khách ---
    debt_rows = []

    # Phơi chính mà khách là chủ hàng
    main_phois = (
        Phoi.query
        .filter_by(status='confirmed', customer_id=customer_id)
        .order_by(Phoi.departure_date.desc(), Phoi.id.desc())
        .all()
    )
    for phoi in main_phois:
        rf = phoi.revenue_full or Decimal('0')
        rc = (phoi.revenue_collected or Decimal('0')) + (phoi.manager_revenue_collected or Decimal('0'))
        outstanding = rf - rc
        debt_rows.append({
            'phoi': phoi,
            'return_trip': None,
            'revenue_full': rf,
            'revenue_collected': rc,
            'outstanding': outstanding,
            'date': phoi.departure_date,
            'truck_number': phoi.truck.license_plate if phoi.truck else '',
        })

    # Chuyến về mà khách là chủ hàng (khác với phơi chính)
    return_trips = (
        PhoiReturnTrip.query
        .filter_by(customer_id=customer_id)
        .join(Phoi, PhoiReturnTrip.phoi_id == Phoi.id)
        .filter(Phoi.status == 'confirmed')
        .order_by(PhoiReturnTrip.return_date.desc(), PhoiReturnTrip.id.desc())
        .all()
    )
    for rt in return_trips:
        # Bỏ qua nếu phơi chính cũng thuộc khách này (tránh đếm 2 lần nếu cùng khách)
        rf = rt.revenue_full or Decimal('0')
        rc = (rt.revenue_collected or Decimal('0')) + (rt.manager_revenue_collected or Decimal('0'))
        outstanding = rf - rc
        debt_rows.append({
            'phoi': rt.phoi,
            'return_trip': rt,
            'revenue_full': rf,
            'revenue_collected': rc,
            'outstanding': outstanding,
            'date': rt.return_date or rt.phoi.departure_date,
            'truck_number': rt.phoi.truck.license_plate if rt.phoi.truck else '',
        })

    # Sắp xếp: mới nhất trước
    debt_rows.sort(key=lambda r: (r['date'] or r['phoi'].departure_date), reverse=True)

    # Chỉ lấy các dòng còn nợ (outstanding > 0)
    debt_rows_with_debt = [r for r in debt_rows if r['outstanding'] > 0]
    all_rows = debt_rows_with_debt
    total_outstanding = sum((r['outstanding'] for r in all_rows), Decimal('0'))
    total_revenue_full = sum((r['revenue_full'] for r in all_rows), Decimal('0'))
    total_revenue_collected = sum((r['revenue_collected'] for r in all_rows), Decimal('0'))

    displayed_rows = all_rows if show_all else all_rows[:20]
    has_more = len(all_rows) > 20 and not show_all

    return render_template(
        'debts/customer_detail.html',
        customer=customer,
        rows=displayed_rows,
        total_outstanding=total_outstanding,
        total_revenue_full=total_revenue_full,
        total_revenue_collected=total_revenue_collected,
        total_count=len(all_rows),
        show_all=show_all,
        has_more=has_more,
    )


@bp.route('/debts/customer/<int:customer_id>/collect', methods=['POST'])
@login_required
def collect_payment(customer_id):
    """Thu tiền từ khách — phân bổ vào manager_revenue_collected của các phơi cũ nhất trước."""
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền thực hiện thao tác này.', 'danger')
        return redirect(url_for('phoi.index'))

    customer = Customer.query.get_or_404(customer_id)

    try:
        amount_str = request.form.get('amount', '').strip().replace(',', '')
        amount = Decimal(amount_str)
        if amount <= 0:
            raise ValueError
    except (InvalidOperation, ValueError):
        flash('Số tiền không hợp lệ.', 'danger')
        return redirect(url_for('debts.customer_detail', customer_id=customer_id))

    notes = request.form.get('notes', '').strip()

    # --- Thu thập tất cả dòng còn nợ, sắp xếp CŨ NHẤT trước để phân bổ ---
    debt_rows = []

    main_phois = (
        Phoi.query
        .filter_by(status='confirmed', customer_id=customer_id)
        .order_by(Phoi.departure_date.asc(), Phoi.id.asc())
        .all()
    )
    for phoi in main_phois:
        rf = phoi.revenue_full or Decimal('0')
        rc = (phoi.revenue_collected or Decimal('0')) + (phoi.manager_revenue_collected or Decimal('0'))
        if rf - rc > 0:
            debt_rows.append({'type': 'phoi', 'obj': phoi, 'outstanding': rf - rc})

    return_trips = (
        PhoiReturnTrip.query
        .filter_by(customer_id=customer_id)
        .join(Phoi, PhoiReturnTrip.phoi_id == Phoi.id)
        .filter(Phoi.status == 'confirmed')
        .order_by(PhoiReturnTrip.return_date.asc(), PhoiReturnTrip.id.asc())
        .all()
    )
    for rt in return_trips:
        rf = rt.revenue_full or Decimal('0')
        rc = (rt.revenue_collected or Decimal('0')) + (rt.manager_revenue_collected or Decimal('0'))
        if rf - rc > 0:
            debt_rows.append({'type': 'return_trip', 'obj': rt, 'outstanding': rf - rc})

    # Sắp xếp cũ nhất trước
    def row_date(r):
        obj = r['obj']
        if r['type'] == 'phoi':
            return (obj.departure_date, obj.id)
        return (obj.return_date or obj.phoi.departure_date, obj.id)

    debt_rows.sort(key=row_date)

    # --- Phân bổ tiền ---
    remaining = amount
    for row in debt_rows:
        if remaining <= 0:
            break
        obj = row['obj']
        can_apply = min(remaining, row['outstanding'])
        obj.manager_revenue_collected = (obj.manager_revenue_collected or Decimal('0')) + can_apply
        remaining -= can_apply

    db.session.commit()

    applied = amount - remaining
    msg = f'Đã ghi nhận thu {"{:,.0f}".format(applied)} đ từ {customer.name}.'
    if remaining > 0:
        msg += f' Lưu ý: {"{:,.0f}".format(remaining)} đ vượt quá tổng nợ và chưa được phân bổ.'
    if notes:
        msg += f' Ghi chú: {notes}.'
    flash(msg, 'success')
    return redirect(url_for('debts.customer_detail', customer_id=customer_id))
