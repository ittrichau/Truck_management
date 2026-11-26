"""Private planning and reconciliation screens for managers/admins."""
from calendar import monthrange
from datetime import datetime, timezone, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app import db
from app.access import customers_query, drivers_query, phois_query, trucks_query
from app.models import Customer, Phoi, Truck, User
from app.planning_view import ScheduleView, calendar_data, live_data as plan_live_data, matches
from app.trip_planning import (
    TripPlan, actual_from_phoi, form_values, parse_day, parse_id,
    candidate_phois, sync_phoi, unique_candidate,
)


bp = Blueprint('planning', __name__, url_prefix='/planning')


@bp.before_request
@login_required
def require_manager():
    if current_user.role not in ('manager', 'admin'):
        abort(403)


def plans_query():
    query = TripPlan.query
    if not current_user.is_admin():
        query = query.filter(TripPlan.manager_id == current_user.id,
                             TripPlan.truck_id.in_(trucks_query().with_entities(Truck.id)))
        # A manually linked phơi must remain in the same manager's scope after transfers.
        query = query.filter(or_(TripPlan.phoi_id.is_(None), TripPlan.phoi_id.in_(phois_query().with_entities(Phoi.id))))
    return query


def plan_or_404(identity, lock=False):
    query = plans_query().filter_by(id=identity)
    return (query.with_for_update() if lock else query).first_or_404()


def check_version(plan):
    if parse_id(request.form.get('version'), 'Phiên bản kế hoạch', True) != plan.version:
        raise ValueError('Kế hoạch vừa thay đổi. Vui lòng tải lại trang và kiểm tra trước khi lưu.')


def reason():
    value = request.form.get('reason', '').strip()
    if not value or len(value) > 500:
        raise ValueError('Vui lòng nhập lý do xử lý, tối đa 500 ký tự.')
    return value


def live_data(plan):
    return plan_live_data(db.session, plan)


def catalogs(plan=None):
    trucks = trucks_query().order_by(Truck.license_plate).all()
    drivers = drivers_query().order_by(User.full_name).all()
    customers = customers_query(include_history=True).order_by(Customer.name).all()
    # Keep the plan's historical choices editable without opening the customer's catalog.
    if plan:
        ids = {plan.customer_id} | {row.get('customer_id') for row in plan.return_trips or []}
        existing_ids = {customer.id for customer in customers}
        customers += Customer.query.filter(Customer.id.in_(ids - existing_ids - {None})).all()
    return dict(trucks=trucks, drivers=drivers, customers=customers)


def selected_filters():
    now = datetime.now(timezone(timedelta(hours=7))).date()
    start = parse_day(request.args.get('start_date', now.replace(day=1).isoformat()), 'Từ ngày', True)
    end = parse_day(request.args.get('end_date', now.replace(day=monthrange(now.year, now.month)[1]).isoformat()), 'Đến ngày', True)
    if end < start or (end - start).days > 366:
        raise ValueError('Khoảng lọc phải đúng thứ tự và tối đa 366 ngày.')
    filters = dict(start_date=start.isoformat(), end_date=end.isoformat(),
                   q=request.args.get('q', '').strip()[:200], status=request.args.get('status', ''))
    if filters['status'] not in ('', 'planned', 'running', 'matched', 'review', 'reviewed', 'cancelled', 'outside'):
        raise ValueError('Trạng thái lọc không hợp lệ.')
    for field, query in (('truck_id', trucks_query()), ('driver_id', drivers_query()),
                         ('customer_id', customers_query(include_history=True))):
        identity = parse_id(request.args.get(field), 'Bộ lọc')
        if identity and not query.filter_by(id=identity).first():
            abort(404)
        filters[field] = identity
    return start, end, filters


@bp.route('')
def index():
    options = catalogs()
    try:
        start, end, filters = selected_filters()
    except ValueError as exc:
        return render_template('planning/index.html', error=str(exc), rows=[], outside=[],
                               filters=request.args, page=1, pages=1, total=0, **options), 400
    # Include trips crossing the period and actual dates moved outside their planned period.
    query = plans_query().outerjoin(Phoi, TripPlan.phoi_id == Phoi.id).filter(or_(
        (TripPlan.departure_date <= end) & (or_(TripPlan.return_date.is_(None), TripPlan.return_date >= start)),
        (Phoi.departure_date <= end) & (or_(Phoi.return_date.is_(None), Phoi.return_date >= start)),
    ))
    plans = query.order_by(TripPlan.departure_date, TripPlan.id).all()
    all_plans = plans_query().filter_by(is_cancelled=False).all()
    rows = ScheduleView(db.session).rows(plans, all_plans, start, end, filters)

    outside = []
    if filters['status'] in ('', 'outside', 'review'):
        used = select(TripPlan.phoi_id).where(TripPlan.phoi_id.isnot(None))
        phois = phois_query().filter(Phoi.status != 'cancelled', ~Phoi.id.in_(used),
                                     Phoi.departure_date <= end,
                                     or_(Phoi.return_date.is_(None), Phoi.return_date >= start)).order_by(Phoi.departure_date).all()
        for phoi in phois:
            actual = actual_from_phoi(phoi)
            if matches(actual, filters):
                outside.append(dict(phoi=phoi, actual=actual))
    total = len(rows)
    try:
        page = parse_id(request.args.get('page', '1'), 'Trang', True)
    except ValueError:
        abort(400)
    pages = max(1, (total + 29) // 30)
    page = min(page, pages)
    pagination = dict(filters, page=page)
    rows = rows[(page - 1) * 30:page * 30]
    days = calendar_data(rows, start, end)
    return render_template('planning/index.html', rows=rows, outside=outside, days=days,
                           filters=filters, page=page, pages=pages, total=total, pagination=pagination,
                           today=datetime.now(timezone(timedelta(hours=7))).date().isoformat(), **options)


@bp.route('/create', methods=['GET', 'POST'])
def create():
    error = None
    if request.method == 'POST':
        try:
            values = form_values(request.form, current_user)
            plan = TripPlan(**values, created_by_id=current_user.id)
            db.session.add(plan)
            db.session.flush()
            plan.original_data = plan.planned_data(db.session)
            plan.record(db.session, 'create', None, 'Lập kế hoạch', current_user.id)
            # A manager can also enter a plan after a matching phơi was submitted.
            candidate = unique_candidate(db.session, plan)
            if candidate and candidate.status in ('submitted', 'confirmed'):
                sync_phoi(db.session, candidate.id, current_user.id)
            db.session.commit()
            flash('Đã lập kế hoạch chuyến hàng.', 'success')
            return redirect(url_for('planning.detail', id=plan.id))
        except (ValueError, IntegrityError, StaleDataError) as exc:
            db.session.rollback()
            error = str(exc) if isinstance(exc, ValueError) else 'Dữ liệu vừa thay đổi. Vui lòng tải lại và kiểm tra.'
    return render_template('planning/form.html', plan=None, error=error, form=request.form, **catalogs()), 400 if error else 200


@bp.route('/<int:id>')
def detail(id):
    plan = plan_or_404(id)
    actual, phoi = live_data(plan)
    status, label = plan.status(db.session, actual, bool(phoi and phoi.status == 'draft'))
    available = phois_query().join(Truck).filter(Truck.manager_id == plan.manager_id, Phoi.status != 'cancelled')
    used = select(TripPlan.phoi_id).where(TripPlan.phoi_id.isnot(None), TripPlan.id != plan.id)
    available = available.filter(~Phoi.id.in_(used)).order_by(Phoi.departure_date.desc()).all()
    return render_template('planning/detail.html', plan=plan, planned=plan.planned_data(db.session),
                           actual=actual, phoi=phoi, status=status, label=label,
                           differences=plan.differences(db.session, actual), available=available,
                           suggestions=candidate_phois(db.session, plan) if not plan.phoi_id else [],
                           actual_signature=plan.signature(db.session, actual) if actual else '')


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    plan = plan_or_404(id, request.method == 'POST')
    error = None
    if request.method == 'POST':
        try:
            check_version(plan)
            if plan.is_cancelled:
                raise ValueError('Kế hoạch đã hủy không thể chỉnh sửa.')
            why = reason()
            values = form_values(request.form, current_user, plan)
            before = plan.audit_data(db.session)
            for key, value in values.items():
                setattr(plan, key, value)
            plan.reviewed_signature = None
            plan.record(db.session, 'edit', before, why, current_user.id)
            db.session.commit()
            flash('Đã cập nhật kế hoạch; phơi tài xế được giữ nguyên.', 'success')
            return redirect(url_for('planning.detail', id=id))
        except (ValueError, IntegrityError, StaleDataError) as exc:
            db.session.rollback()
            error = str(exc) if isinstance(exc, ValueError) else 'Dữ liệu vừa thay đổi. Vui lòng tải lại và kiểm tra.'
    return render_template('planning/form.html', plan=plan, error=error, form=request.form, **catalogs(plan)), 400 if error else 200


@bp.route('/<int:id>/action', methods=['POST'])
def action(id):
    plan = plan_or_404(id, True)
    try:
        check_version(plan)
        operation = request.form.get('action')
        if operation == 'sync':
            if not plan.phoi_id:
                candidate = unique_candidate(db.session, plan)
                if not candidate or candidate.status not in ('submitted', 'confirmed'):
                    raise ValueError('Chưa có phơi đã chốt khớp duy nhất. Hãy chọn phơi để liên kết.')
                sync_phoi(db.session, candidate.id, current_user.id)
            else:
                if plan.phoi.truck.manager_id != plan.manager_id:
                    raise ValueError('Phơi đã chuyển sang quản lý khác; hãy kiểm tra liên kết.')
                sync_phoi(db.session, plan.phoi_id, current_user.id)
        elif operation == 'link':
            phoi_id = parse_id(request.form.get('phoi_id'), 'Phơi', True)
            phoi = phois_query().filter_by(id=phoi_id).first_or_404()
            plan.link_phoi(db.session, phoi, current_user.id, reason())
        elif operation == 'unlink':
            why = reason()
            before = plan.audit_data(db.session)
            plan.phoi_id = None
            plan.actual_data = None
            plan.synced_at = None
            plan.reviewed_signature = None
            plan.record(db.session, 'unlink', before, why, current_user.id)
        elif operation in ('accept', 'review'):
            plan.review(db.session, current_user.id, reason(), request.form.get('actual_signature'),
                        accept=operation == 'accept')
        elif operation == 'cancel':
            why = reason()
            before = plan.audit_data(db.session)
            plan.is_cancelled = True
            plan.record(db.session, 'cancel', before, why, current_user.id)
        else:
            raise ValueError('Thao tác không hợp lệ.')
        db.session.commit()
        flash('Đã cập nhật kế hoạch và lưu lịch sử xử lý.', 'success')
    except (ValueError, IntegrityError, StaleDataError) as exc:
        db.session.rollback()
        flash(str(exc) if isinstance(exc, ValueError) else 'Dữ liệu vừa thay đổi hoặc phơi đã được liên kết. Vui lòng tải lại.', 'danger')
    return redirect(url_for('planning.detail', id=id))
