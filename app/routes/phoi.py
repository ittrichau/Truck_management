from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from sqlalchemy import or_
from app import db
from app.models import ActivityLog, Phoi, PhoiAttachment, PhoiExpense, PhoiReturnTrip, FuelLog, Customer, Truck, User, generate_phoi_number
from app.phoi_attachments import attachment_path, delete_attachment_file, save_phoi_attachment
from app.phoi_repair_expenses import _sync_standard_expenses, _sync_repair_expenses, _save_repair_receipts
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

bp = Blueprint('phoi', __name__)


def can_manage_phoi(user, phoi):
    return user.is_manager_or_admin() or (user.is_driver() and phoi.driver_id == user.id)


def submission_error(phoi):
    if phoi.return_trips.count() == 0:
        return 'Phơi chưa có chuyến về. Vui lòng thêm ít nhất một chuyến về trước khi chốt.'
    # FuelLog.phois creates this backref as a regular list, not a query.
    if not phoi.fuel_logs:
        return 'Phơi chưa được gắn lần đổ xăng nào. Vui lòng ghi nhận đổ xăng trước khi chốt.'
    if not phoi.km_end or phoi.km_end <= 0:
        return 'Vui l\u00f2ng nh\u1eadp KM cu\u1ed1i h\u1ee3p l\u1ec7 tr\u01b0\u1edbc khi ch\u1ed1t ph\u01a1i.'
    return None


def financial_confirmation_error(phoi):
    """Return the first missing or inconsistent financial datum needed to finalize a phơi."""
    trips = [phoi, *phoi.return_trips.all()]
    for index, trip in enumerate(trips):
        trip_label = 'chuyến đi' if index == 0 else f'chuyến về #{trip.trip_order}'
        if trip.payment_method == 'fixed':
            if trip.revenue_full is None or trip.revenue_full <= 0:
                return f'Vui lòng nhập doanh thu bao chuyến lớn hơn 0 cho {trip_label} trước khi xác nhận.'
        elif trip.payment_method == 'per_ton':
            if trip.cargo_weight_tons is None or trip.cargo_weight_tons <= 0:
                return f'Vui lòng nhập số tấn lớn hơn 0 cho {trip_label} trước khi xác nhận.'
            if trip.price_per_ton is None or trip.price_per_ton <= 0:
                return f'Vui lòng nhập đơn giá mỗi tấn lớn hơn 0 cho {trip_label} trước khi xác nhận.'
        else:
            return f'Cách tính tiền của {trip_label} không hợp lệ.'
        driver_collected = trip.revenue_collected or Decimal('0')
        manager_collected = trip.manager_revenue_collected or Decimal('0')
        if driver_collected < 0 or manager_collected < 0:
            return f'Tiền đã thu của {trip_label} không thể âm.'
        if driver_collected + manager_collected > trip.revenue_full:
            return f'Tổng tiền tài xế và quản lý đã thu của {trip_label} không thể lớn hơn doanh thu full.'
    return None

def _sync_confirmation_toll_fee(phoi):
    """Record the manager's explicit toll decision for the entire phơi."""
    toll_status = request.form.get('toll_fee_status')
    existing_expense = PhoiExpense.query.filter_by(phoi_id=phoi.id, category='toll_fee').first()

    if toll_status == 'incurred':
        amount = _money(request.form.get('toll_fee_amount', ''))
        if amount <= 0:
            raise ValueError('Vui lòng nhập tổng phí đường toàn phơi lớn hơn 0.')
        if existing_expense:
            existing_expense.amount = amount
            existing_expense.description = 'Phí đường toàn phơi'
        else:
            db.session.add(PhoiExpense(
                phoi_id=phoi.id,
                category='toll_fee',
                description='Phí đường toàn phơi',
                amount=amount,
            ))
    elif toll_status == 'none':
        if existing_expense:
            db.session.delete(existing_expense)
    else:
        raise ValueError('Vui lòng xác nhận phơi có phát sinh phí đường hay không.')

def update_truck_status(truck):
    if not truck:
        return
    has_active_phoi = Phoi.query.filter(
        Phoi.truck_id == truck.id,
        Phoi.status.in_(['draft', 'submitted'])
    ).count() > 0
    truck.status = 'in_trip' if has_active_phoi else 'available'



def _unallocated_fuel_logs(truck_id=None):
    """Fuel released by a cancelled phơi and awaiting manager allocation."""
    query = FuelLog.query.filter(
        FuelLog.allocation_status == 'unallocated',
        FuelLog.unallocated_from_cancelled_phoi_id.isnot(None),
    )
    if truck_id:
        query = query.filter_by(truck_id=truck_id)
    return query.order_by(FuelLog.refuel_date.desc(), FuelLog.id.desc()).all()

def _assign_unallocated_fuel_logs(phoi):
    """Manager assigns same-truck fuel fills released by a cancelled phơi."""
    selected_ids = request.form.getlist('unallocated_fuel_log_ids', type=int)
    if not selected_ids:
        return
    if not current_user.is_manager_or_admin():
        raise ValueError('Chỉ quản lý mới được phân bổ lại lần đổ xăng từ phơi đã hủy.')
    logs = FuelLog.query.filter(FuelLog.id.in_(selected_ids)).all()
    if len(logs) != len(set(selected_ids)):
        raise ValueError('Có lần đổ xăng chờ phân bổ không tồn tại.')
    for log in logs:
        if (
            log.allocation_status != 'unallocated'
            or not log.unallocated_from_cancelled_phoi_id
            or log.truck_id != phoi.truck_id
        ):
            raise ValueError('Chỉ được phân bổ xăng được tách từ phơi đã hủy của cùng xe.')
        log.phois.append(phoi)
        log.allocation_status = 'allocated'
        log.unallocated_from_cancelled_phoi_id = None

def _ensure_truck_has_no_other_active_phoi(truck_id, excluded_phoi_id=None):
    """A truck may have only one in-progress draft phơi at a time."""
    query = Phoi.query.filter(
        Phoi.truck_id == truck_id,
        Phoi.status == 'draft'
    )
    if excluded_phoi_id:
        query = query.filter(Phoi.id != excluded_phoi_id)
    active_phoi = query.order_by(Phoi.created_at.desc()).first()
    if active_phoi:
        raise ValueError(
            f'Xe đang có phơi {active_phoi.phoi_number} ở trạng thái '
            'đang thực hiện. Hãy chốt phơi này trước khi tạo phơi mới.'
        )

def _record_km_start_warning(phoi, baseline_km, entered_km):
    """Record an admin-visible alert for a large driver odometer correction."""
    difference = abs(entered_km - baseline_km)
    if not current_user.is_driver() or difference <= 50:
        return
    db.session.add(ActivityLog(
        user_id=current_user.id,
        username=current_user.username,
        action='ALERT',
        resource_type='phoi_km_warning',
        resource_id=str(phoi.id),
        details=(
            f'CẢNH BÁO KM: Tài xế sửa KM đầu phơi {phoi.phoi_number} '
            f'của xe {phoi.truck.license_plate} từ {baseline_km:,} thành '
            f'{entered_km:,} km (chênh {difference:,} km).'
        ),
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:200],
        method=request.method,
        endpoint=request.endpoint,
        status_code=200,
    ))

def _active_phoi_options():
    """Return active trucks, drivers, and each truck's default driver."""
    trucks = Truck.query.filter_by(is_active=True).order_by(Truck.license_plate).all()
    drivers = User.query.filter_by(role='driver', is_active=True).order_by(User.full_name).all()
    driver_by_truck_id = {
        driver.current_truck_id: driver
        for driver in drivers
        if driver.current_truck_id
    }
    return trucks, drivers, driver_by_truck_id


def _selected_driver_and_truck():
    """Validate and resolve the driver/truck pair from the phơi form."""
    is_substitute = request.form.get('is_substitute') == '1'
    truck_id = request.form.get('truck_id', type=int) or request.form.get('locked_truck_id', type=int)
    if not truck_id:
        raise ValueError('Vui lòng chọn xe.')

    truck = Truck.query.filter_by(id=truck_id, is_active=True).first()
    if not truck:
        raise ValueError('Xe được chọn không tồn tại hoặc đã ngừng hoạt động.')

    if current_user.is_driver():
        driver = current_user
        if not is_substitute:
            if not driver.current_truck_id:
                raise ValueError('Bạn chưa được gán xe mặc định. Hãy bật chế độ chạy giùm để chọn xe.')
            if truck.id != driver.current_truck_id:
                raise ValueError('Khi chưa bật chạy giùm, bạn chỉ được tạo phơi cho xe mặc định.')
        return driver, truck, is_substitute

    if not current_user.is_manager_or_admin():
        raise ValueError('Bạn không có quyền tạo hoặc sửa phơi.')

    if is_substitute:
        driver_id = request.form.get('driver_id', type=int)
        if not driver_id:
            raise ValueError('Vui lòng chọn tài xế chạy giùm.')
        driver = User.query.filter_by(id=driver_id, role='driver', is_active=True).first()
        if not driver:
            raise ValueError('Tài xế được chọn không tồn tại hoặc đã ngừng hoạt động.')
        return driver, truck, True

    driver = User.query.filter_by(current_truck_id=truck.id, role='driver', is_active=True).first()
    if not driver:
        raise ValueError('Xe này chưa được gán tài xế mặc định. Hãy gán tài xế hoặc bật chế độ chạy giùm.')
    return driver, truck, False


def _money(value):
    """Parse a currency form field after removing visual thousand separators."""
    try:
        return Decimal(str(value or '0').replace(',', '').strip() or '0')
    except (InvalidOperation, ValueError):
        raise ValueError('Số tiền không hợp lệ.')


def _revenue_from_form(method, fixed_revenue, weight, price_per_ton):
    """Parse revenue while allowing an owner to finalize a per-ton price later."""
    if method not in ('fixed', 'per_ton'):
        raise ValueError('Cách tính tiền không hợp lệ.')
    if method == 'fixed':
        return _money(fixed_revenue), None, None

    try:
        tons = Decimal(str(weight).strip()) if str(weight or '').strip() else None
    except InvalidOperation:
        raise ValueError('Số tấn không hợp lệ.')
    price = _money(price_per_ton) if str(price_per_ton or '').strip() else None
    if tons is not None and tons < 0:
        raise ValueError('Số tấn không thể âm.')
    if price is not None and price < 0:
        raise ValueError('Đơn giá mỗi tấn không thể âm.')
    revenue = tons * price if tons is not None and price is not None else Decimal('0')
    return revenue, tons, price


def _save_return_trip_weigh_tickets(phoi, synced_trips, saved_keys):
    """Lưu tối đa năm ảnh phiếu cân cho từng chuyến về đã gửi."""
    for form_index, trip in synced_trips:
        files = [file for file in request.files.getlist(f'return_trip_weigh_ticket_images_{form_index}') if file and file.filename]
        if len(files) > 5:
            raise ValueError(f'Ảnh phiếu cân chuyến về #{trip.trip_order} chỉ được tải tối đa 5 ảnh.')
        for file in files:
            metadata = save_phoi_attachment(file, phoi.id)
            saved_keys.append(metadata['storage_key'])
            db.session.add(PhoiAttachment(
                phoi_id=phoi.id,
                return_trip_id=trip.id,
                attachment_type='weigh_ticket',
                uploaded_by_id=current_user.id,
                **metadata,
            ))


def _sync_return_trips(phoi):
    """Lưu các chuyến về và giữ nguyên ID/chứng từ của chuyến còn tồn tại."""
    existing_trips = {str(trip.id): trip for trip in phoi.return_trips.all()}
    retained_trip_ids = set()

    trip_ids = request.form.getlist('return_trip_id[]')
    dates = request.form.getlist('return_trip_date[]')
    customer_ids = request.form.getlist('return_trip_customer_id[]')
    origins = request.form.getlist('return_trip_origin[]')
    destinations = request.form.getlist('return_trip_destination[]')
    cargoes = request.form.getlist('return_trip_cargo[]')
    payment_methods = request.form.getlist('return_trip_payment_method[]')
    weights = request.form.getlist('return_trip_cargo_weight_tons[]')
    prices_per_ton = request.form.getlist('return_trip_price_per_ton[]')
    revenues = request.form.getlist('return_trip_revenue_full[]')
    collecteds = request.form.getlist('return_trip_revenue_collected[]')
    manager_collecteds = request.form.getlist('return_trip_manager_revenue_collected[]')
    porter_fees = request.form.getlist('return_trip_porter_fee[]')
    notes = request.form.getlist('return_trip_notes[]')
    synced_trips = []

    for index, origin in enumerate(origins):
        origin = origin.strip()
        destination = destinations[index].strip() if index < len(destinations) else ''
        if not origin and not destination:
            continue
        if not origin or not destination:
            raise ValueError(f'Chuyến về #{index + 1} phải có đủ điểm đi và điểm đến.')

        customer_id = customer_ids[index] if index < len(customer_ids) else ''
        payment_method = payment_methods[index] if index < len(payment_methods) else 'fixed'
        revenue_full, cargo_weight_tons, price_per_ton = _revenue_from_form(
            payment_method,
            revenues[index] if index < len(revenues) else 0,
            weights[index] if index < len(weights) else '',
            prices_per_ton[index] if index < len(prices_per_ton) else 0,
        )
        submitted_trip_id = trip_ids[index] if index < len(trip_ids) else ''
        trip = existing_trips.get(submitted_trip_id)
        if trip:
            retained_trip_ids.add(trip.id)
        else:
            trip = PhoiReturnTrip(phoi_id=phoi.id)
            db.session.add(trip)

        trip.customer_id = int(customer_id) if customer_id else None
        trip.trip_order = index + 1
        trip.return_date = datetime.strptime(dates[index], '%Y-%m-%d').date() if index < len(dates) and dates[index] else None
        trip.origin = origin
        trip.destination = destination
        trip.cargo_description = cargoes[index].strip() if index < len(cargoes) else ''
        trip.payment_method = payment_method
        trip.cargo_weight_tons = cargo_weight_tons
        trip.price_per_ton = price_per_ton
        trip.revenue_full = revenue_full
        trip.revenue_collected = _money(collecteds[index] if index < len(collecteds) else 0)
        if index < len(manager_collecteds):
            trip.manager_revenue_collected = _money(manager_collecteds[index])
        trip.porter_fee = _money(porter_fees[index] if index < len(porter_fees) else 0)
        trip.notes = notes[index].strip() if index < len(notes) else ''
        synced_trips.append((index, trip))

    for trip in existing_trips.values():
        if trip.id not in retained_trip_ids:
            db.session.delete(trip)


    return synced_trips

@bp.route('/')
@bp.route('/phoi')
@login_required
def index():
    """Danh sách phơi – driver chỉ thấy của mình, manager/admin thấy tất cả."""
    page = request.args.get('page', 1, type=int)
    search = request.args.get('q', '').strip()
    filter_status = request.args.get('status', 'active')
    filter_truck_id = request.args.get('truck_id', type=int)
    filter_driver_id = request.args.get('driver_id', type=int)
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')

    query = Phoi.query
    if not current_user.is_manager_or_admin():
        query = query.filter(Phoi.driver_id == current_user.id)

    if search:
        keyword = f'%{search}%'
        query = query.outerjoin(Truck).outerjoin(User, Phoi.driver_id == User.id).filter(
            or_(
                Phoi.phoi_number.ilike(keyword),
                Phoi.origin.ilike(keyword),
                Phoi.destination.ilike(keyword),
                Truck.license_plate.ilike(keyword),
                User.full_name.ilike(keyword),
            )
        )
    if filter_status == 'active':
        query = query.filter(Phoi.status.in_(['draft', 'submitted']))
    elif filter_status in ('draft', 'submitted', 'confirmed', 'cancelled'):
        query = query.filter(Phoi.status == filter_status)
    if filter_truck_id:
        query = query.filter(Phoi.truck_id == filter_truck_id)
    if current_user.is_manager_or_admin() and filter_driver_id:
        query = query.filter(Phoi.driver_id == filter_driver_id)
    if start_date:
        try:
            query = query.filter(Phoi.departure_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        except ValueError:
            start_date = ''
    if end_date:
        try:
            query = query.filter(Phoi.departure_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        except ValueError:
            end_date = ''

    phois = query.order_by(Phoi.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    trucks = Truck.query.order_by(Truck.license_plate).all()
    drivers = User.query.filter_by(role='driver').order_by(User.full_name).all() if current_user.is_manager_or_admin() else []

    balances = {}
    for p in phois.items:
        balances[p.id] = p.balance()

    # Lấy cảnh báo hết hạn đăng kiểm/phù hiệu (chỉ hiện khi đã quá 2 ngày kể từ lần thông báo cuối)
    warnings = []
    notified_truck_ids = set()
    notified_types = {}
    for truck in Truck.query.filter_by(is_active=True).all():
        insp_days = truck.inspection_days_until_expiry()
        if insp_days is not None and insp_days <= 15 and truck.inspection_should_notify():
            label = 'Đăng kiểm' if insp_days >= 0 else 'Đăng kiểm (quá hạn)'
            warnings.append((truck.license_plate, label, abs(insp_days)))
            notified_truck_ids.add(truck.id)
            notified_types.setdefault(truck.id, []).append('inspection')

        perm_days = truck.permit_days_until_expiry()
        if perm_days is not None and perm_days <= 15 and truck.permit_should_notify():
            label = 'Phù hiệu' if perm_days >= 0 else 'Phù hiệu (quá hạn)'
            warnings.append((truck.license_plate, label, abs(perm_days)))
            notified_truck_ids.add(truck.id)
            notified_types.setdefault(truck.id, []).append('permit')

    # Mark notified trucks so we don't notify again for 2 days
    if warnings:
        Truck.mark_expiry_notified(notified_truck_ids, notified_types)
        db.session.commit()

    return render_template(
        'phoi/index.html',
        phois=phois,
        balances=balances,
        expiry_warnings=warnings,
        trucks=trucks,
        drivers=drivers,
        search=search,
        filter_status=filter_status,
        filter_truck_id=filter_truck_id,
        filter_driver_id=filter_driver_id,
        start_date=start_date,
        end_date=end_date,
    )


@bp.route('/phoi/create', methods=['GET', 'POST'])
@login_required
def create():
    """Tạo phơi – driver tự tạo cho mình, manager/admin tạo cho tài xế"""
    if current_user.is_driver():
        # Driver chỉ tạo cho chính mình
        pass
    elif current_user.is_manager_or_admin():
        # Manager/admin có thể tạo cho bất kỳ tài xế nào
        pass
    else:
        flash('Bạn không có quyền tạo phơi.', 'danger')
        return redirect(url_for('phoi.index'))

    trucks, drivers, driver_by_truck_id = _active_phoi_options()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        saved_keys = []
        try:
            driver, truck, is_substitute = _selected_driver_and_truck()
            _ensure_truck_has_no_other_active_phoi(truck.id)
            phoi = Phoi()
            phoi.phoi_number = generate_phoi_number()
            phoi.driver_id = driver.id
            phoi.truck_id = truck.id
            phoi.is_substitute = is_substitute
            phoi.created_by_id = current_user.id
            phoi.customer_id = request.form.get('customer_id') or None
            if phoi.customer_id:
                phoi.customer_id = int(phoi.customer_id)

            dep = request.form.get('departure_date', '')
            ret = request.form.get('return_date', '')
            phoi.departure_date = datetime.strptime(dep, '%Y-%m-%d').date() if dep else date.today()
            phoi.return_date = datetime.strptime(ret, '%Y-%m-%d').date() if ret else None

            phoi.origin = request.form.get('origin', '').strip()
            phoi.destination = request.form.get('destination', '').strip()
            phoi.cargo_description = request.form.get('cargo_description', '').strip()

            # Xe reset KM theo từng phơi; chỉ ghi KM cuối khi xe về bãi.
            phoi.km_start = 0
            phoi.km_end = int(request.form.get('km_end', 0) or 0)
            phoi.calculate_km_total()
            phoi.payment_method = request.form.get('payment_method', 'fixed')
            phoi.revenue_full, cargo_weight_tons, phoi.price_per_ton = _revenue_from_form(
                phoi.payment_method,
                request.form.get('revenue_full', 0),
                request.form.get('cargo_weight_tons', ''),
                request.form.get('price_per_ton', 0),
            )
            phoi.cargo_weight_tons = cargo_weight_tons
            phoi.revenue_collected = _money(request.form.get('revenue_collected', 0))

            # Phơi mới đang thực hiện; chuyến về và đổ xăng sẽ được thêm sau.
            phoi.status = 'draft'
            phoi.notes = request.form.get('notes', '').strip()

            db.session.add(phoi)
            db.session.flush()
            _assign_unallocated_fuel_logs(phoi)
            synced_return_trips = _sync_return_trips(phoi)
            db.session.flush()
            _save_return_trip_weigh_tickets(phoi, synced_return_trips, saved_keys)

            for attachment_type, field_name, maximum_files in (
                ('weigh_ticket', 'weigh_ticket_images', 5),
            ):
                files = [file for file in request.files.getlist(field_name) if file and file.filename]
                if len(files) > maximum_files:
                    raise ValueError('Ảnh phiếu cân chỉ được tải tối đa 5 ảnh khi tạo phơi.')
                for file in files:
                    metadata = save_phoi_attachment(file, phoi.id)
                    saved_keys.append(metadata['storage_key'])
                    db.session.add(PhoiAttachment(
                        phoi_id=phoi.id,
                        attachment_type=attachment_type,
                        uploaded_by_id=current_user.id,
                        **metadata,
                    ))

            _sync_standard_expenses(phoi)
            repairs = _sync_repair_expenses(phoi)
            _save_repair_receipts(phoi, repairs, saved_keys)

            truck.status = 'in_trip'

            db.session.commit()
            flash(f'Đã tạo phơi {phoi.phoi_number}. Phơi đang thực hiện, hãy thêm chuyến về và lần đổ xăng trước khi chốt.', 'success')
            return redirect(url_for('phoi.index'))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            for storage_key in saved_keys:
                delete_attachment_file(storage_key)
            flash(f'Lỗi khi tạo phơi: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            for storage_key in saved_keys:
                delete_attachment_file(storage_key)
            flash(f'Lỗi khi tạo phơi: {str(e)}', 'danger')

    return render_template(
        'phoi/create.html',
        unallocated_fuel_logs=_unallocated_fuel_logs() if current_user.is_manager_or_admin() else [],
        trucks=trucks,
        customers=customers,
        drivers=drivers,
        driver_by_truck_id=driver_by_truck_id
    )


@bp.route('/phoi/<int:id>')
@login_required
def detail(id):
    phoi = Phoi.query.get_or_404(id)

    if current_user.is_driver() and phoi.driver_id != current_user.id:
        flash('Bạn không có quyền xem phơi này.', 'danger')
        return redirect(url_for('phoi.index'))

    return render_template('phoi/detail.html', phoi=phoi)


@bp.route('/phoi/<int:id>/attachments', methods=['POST'])
@login_required
def upload_attachment(id):
    phoi = Phoi.query.get_or_404(id)
    can_update_attachments = (
        (phoi.status == 'draft' and can_manage_phoi(current_user, phoi))
        or (phoi.status == 'submitted' and current_user.is_manager_or_admin())
    )
    if not can_update_attachments:
        flash('Chỉ chủ xe mới có thể bổ sung chứng từ sau khi phơi đã chốt.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    attachment_type = request.form.get('attachment_type', '')
    if attachment_type not in ('weigh_ticket', 'other'):
        flash('Chỉ có thể tải phiếu cân hoặc chứng từ khác.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    return_trip_id = request.form.get('return_trip_id', type=int)
    return_trip = None
    if return_trip_id:
        if attachment_type != 'weigh_ticket':
            flash('Chỉ có thể gắn phiếu cân cho chuyến về.', 'danger')
            return redirect(url_for('phoi.detail', id=id))
        return_trip = PhoiReturnTrip.query.filter_by(
            id=return_trip_id, phoi_id=phoi.id
        ).first()
        if not return_trip:
            flash('Chuyến về không thuộc phơi này.', 'danger')
            return redirect(url_for('phoi.detail', id=id))

    files = [file for file in request.files.getlist('images') if file and file.filename]
    if not files or len(files) > 5:
        flash('Mỗi lần cần tải từ 1 đến 5 ảnh.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    saved_keys = []
    try:
        for file in files:
            metadata = save_phoi_attachment(file, phoi.id)
            saved_keys.append(metadata['storage_key'])
            db.session.add(PhoiAttachment(
                phoi_id=phoi.id,
                return_trip_id=return_trip.id if return_trip else None,
                attachment_type=attachment_type,
                notes=request.form.get('notes', '').strip() or None,
                uploaded_by_id=current_user.id,
                **metadata,
            ))
        db.session.commit()
        flash(f'Đã tải {len(files)} ảnh {PhoiAttachment.TYPES[attachment_type].lower()}.', 'success')
    except ValueError as exc:
        db.session.rollback()
        for storage_key in saved_keys:
            delete_attachment_file(storage_key)
        flash(str(exc), 'danger')
    except Exception:
        db.session.rollback()
        for storage_key in saved_keys:
            delete_attachment_file(storage_key)
        flash('Không thể xử lý ảnh. Vui lòng thử lại.', 'danger')
    return redirect(url_for('phoi.detail', id=id))

@bp.route('/phoi/<int:id>/attachments/<int:attachment_id>')
@login_required
def view_attachment(id, attachment_id):
    phoi = Phoi.query.get_or_404(id)
    if not can_manage_phoi(current_user, phoi):
        flash('Bạn không có quyền xem chứng từ này.', 'danger')
        return redirect(url_for('phoi.index'))
    attachment = PhoiAttachment.query.filter_by(id=attachment_id, phoi_id=phoi.id).first_or_404()
    try:
        path = attachment_path(attachment.storage_key)
        if not path.is_file():
            raise FileNotFoundError
        return send_file(path, mimetype=attachment.mime_type, conditional=True)
    except (FileNotFoundError, ValueError):
        flash('Không tìm thấy tệp ảnh.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

@bp.route('/phoi/<int:id>/attachments/<int:attachment_id>/delete', methods=['POST'])
@login_required
def delete_attachment(id, attachment_id):
    phoi = Phoi.query.get_or_404(id)
    can_delete_attachment = (
        (phoi.status == 'draft' and can_manage_phoi(current_user, phoi))
        or (phoi.status == 'submitted' and current_user.is_manager_or_admin())
    )
    if not can_delete_attachment:
        flash('Chỉ chủ xe mới có thể xóa chứng từ sau khi phơi đã chốt.', 'danger')
        return redirect(url_for('phoi.detail', id=id))
    attachment = PhoiAttachment.query.filter_by(id=attachment_id, phoi_id=phoi.id).first_or_404()
    if attachment.attachment_type == 'repair_receipt' and attachment.expense and not attachment.expense.is_home_repair:
        if attachment.expense.attachments.filter_by(attachment_type='repair_receipt').count() <= 1:
            flash('Không thể xóa hóa đơn cuối cùng của hạng mục sửa xe bên ngoài.', 'danger')
            return redirect(url_for('phoi.detail', id=id))
    storage_key = attachment.storage_key
    db.session.delete(attachment)
    db.session.commit()
    delete_attachment_file(storage_key)
    flash('Đã xóa ảnh đính kèm.', 'success')
    return redirect(url_for('phoi.detail', id=id))

@bp.route('/phoi/<int:id>/print')
@login_required
def print_view(id):
    phoi = Phoi.query.get_or_404(id)

    if current_user.is_driver() and phoi.driver_id != current_user.id:
        flash('Bạn không có quyền xem phơi này.', 'danger')
        return redirect(url_for('phoi.index'))

    return render_template('phoi/detail_print.html', phoi=phoi)


@bp.route('/phoi/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    phoi = Phoi.query.get_or_404(id)
    can_edit = (
        (phoi.status == 'draft' and can_manage_phoi(current_user, phoi))
        or (phoi.status == 'submitted' and current_user.is_manager_or_admin())
    )
    if not can_edit:
        flash('Tài xế chỉ có thể sửa phơi đang thực hiện; phơi đã xác nhận không thể chỉnh sửa.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    trucks, drivers, driver_by_truck_id = _active_phoi_options()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        saved_keys = []
        try:
            old_truck = phoi.truck
            driver, truck, is_substitute = _selected_driver_and_truck()
            _ensure_truck_has_no_other_active_phoi(truck.id, excluded_phoi_id=phoi.id)
            phoi.driver_id = driver.id
            phoi.truck_id = truck.id
            phoi.is_substitute = is_substitute
            phoi.customer_id = request.form.get('customer_id') or None
            if phoi.customer_id:
                phoi.customer_id = int(phoi.customer_id)

            dep = request.form.get('departure_date', '')
            ret = request.form.get('return_date', '')
            if dep:
                phoi.departure_date = datetime.strptime(dep, '%Y-%m-%d').date()
            if ret:
                phoi.return_date = datetime.strptime(ret, '%Y-%m-%d').date()

            phoi.origin = request.form.get('origin', '').strip()
            phoi.destination = request.form.get('destination', '').strip()
            phoi.cargo_description = request.form.get('cargo_description', '').strip()
            phoi.km_start = 0
            phoi.km_end = int(request.form.get('km_end', 0) or 0)
            phoi.calculate_km_total()
            phoi.payment_method = request.form.get('payment_method', 'fixed')
            phoi.revenue_full, cargo_weight_tons, phoi.price_per_ton = _revenue_from_form(
                phoi.payment_method,
                request.form.get('revenue_full', 0),
                request.form.get('cargo_weight_tons', ''),
                request.form.get('price_per_ton', 0),
            )
            phoi.cargo_weight_tons = cargo_weight_tons
            phoi.revenue_collected = _money(request.form.get('revenue_collected', 0))
            phoi.notes = request.form.get('notes', '').strip()

            if current_user.is_manager_or_admin():
                if 'manager_revenue_collected' in request.form:
                    phoi.manager_revenue_collected = _money(
                        request.form.get('manager_revenue_collected', 0)
                    )
                phoi.driver_wage = _money(request.form.get('driver_wage', 0))

            synced_return_trips = _sync_return_trips(phoi)
            db.session.flush()
            _save_return_trip_weigh_tickets(phoi, synced_return_trips, saved_keys)

            files = [file for file in request.files.getlist('weigh_ticket_images') if file and file.filename]
            if len(files) > 5:
                raise ValueError('Ảnh phiếu cân chỉ được tải tối đa 5 ảnh mỗi lần.')
            for file in files:
                metadata = save_phoi_attachment(file, phoi.id)
                saved_keys.append(metadata['storage_key'])
                db.session.add(PhoiAttachment(
                    phoi_id=phoi.id,
                    attachment_type='weigh_ticket',
                    uploaded_by_id=current_user.id,
                    **metadata,
                ))

            _sync_standard_expenses(phoi)
            repairs = _sync_repair_expenses(phoi)
            _save_repair_receipts(phoi, repairs, saved_keys)
            _assign_unallocated_fuel_logs(phoi)

            if phoi.status == 'submitted' and current_user.is_manager_or_admin():
                db.session.add(ActivityLog(
                    user_id=current_user.id,
                    username=current_user.username,
                    action='UPDATE',
                    resource_type='phoi_reconciliation',
                    resource_id=str(phoi.id),
                    details=(
                        f'Đã đối soát và cập nhật phơi {phoi.phoi_number} đã chốt, gồm thông tin '
                        'chuyến đi, chứng từ, doanh thu, chi phí hoặc phí công tài xế.'
                    ),
                    ip_address=request.remote_addr,
                    user_agent=request.headers.get('User-Agent', '')[:200],
                    method=request.method,
                    endpoint=request.endpoint,
                    status_code=200,
                ))

            update_truck_status(old_truck)
            update_truck_status(truck)
            db.session.commit()
            flash(f'Đã cập nhật phơi {phoi.phoi_number}.', 'success')
            return redirect(url_for('phoi.detail', id=id))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            for storage_key in saved_keys:
                delete_attachment_file(storage_key)
            flash(f'Lỗi: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            for storage_key in saved_keys:
                delete_attachment_file(storage_key)
            flash(f'Lỗi: {str(e)}', 'danger')

    return render_template(
        'phoi/edit.html',
        unallocated_fuel_logs=_unallocated_fuel_logs(phoi.truck_id) if current_user.is_manager_or_admin() else [],
        phoi=phoi,
        trucks=trucks,
        customers=customers,
        drivers=drivers,
        driver_by_truck_id=driver_by_truck_id
    )


@bp.route('/phoi/<int:id>/cancel', methods=['POST'])
@login_required
def cancel(id):
    phoi = Phoi.query.get_or_404(id)
    if not current_user.is_manager_or_admin():
        flash('Chỉ quản lý mới có quyền hủy phơi.', 'danger')
        return redirect(url_for('phoi.detail', id=id))
    if phoi.status != 'draft':
        flash('Chỉ có thể hủy phơi đang thực hiện.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    reason = request.form.get('cancellation_reason', '').strip()
    if not reason:
        flash('Vui lòng nhập lý do hủy phơi.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    try:
        released_count = 0
        for fuel_log in list(phoi.fuel_logs):
            fuel_log.phois.remove(phoi)
            if fuel_log.attached_phoi_count() == 0:
                fuel_log.allocation_status = 'unallocated'
                fuel_log.unallocated_from_cancelled_phoi_id = phoi.id
                released_count += 1

        phoi.status = 'cancelled'
        phoi.cancelled_by_id = current_user.id
        phoi.cancelled_at = datetime.utcnow()
        phoi.cancellation_reason = reason
        update_truck_status(phoi.truck)
        db.session.add(ActivityLog(
            user_id=current_user.id,
            username=current_user.username,
            action='CANCEL',
            resource_type='phoi',
            resource_id=str(phoi.id),
            details=(
                f'Đã hủy phơi {phoi.phoi_number}. Lý do: {reason}. '
                f'{released_count} lần đổ xăng chuyển sang chờ phân bổ.'
            ),
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:200],
            method=request.method,
            endpoint=request.endpoint,
            status_code=200,
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()
        flash('Không thể hủy phơi. Vui lòng thử lại.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    flash(f'Đã hủy phơi {phoi.phoi_number}. {released_count} lần đổ xăng đang chờ phân bổ lại.', 'success')
    return redirect(url_for('phoi.detail', id=id))

@bp.route('/phoi/<int:id>/submit', methods=['POST'])
@login_required
def submit(id):
    phoi = Phoi.query.get_or_404(id)
    if not can_manage_phoi(current_user, phoi):
        flash('Bạn không có quyền chốt phơi này.', 'danger')
        return redirect(url_for('phoi.index'))
    if phoi.status != 'draft':
        flash('Chỉ có thể chốt phơi đang thực hiện.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    error = submission_error(phoi)
    if error:
        flash(error, 'danger')
        return redirect(url_for('phoi.detail', id=id))

    phoi.status = 'submitted'
    update_truck_status(phoi.truck)
    db.session.commit()
    flash(f'Đã chốt phơi {phoi.phoi_number}; đang chờ quản lý xác nhận.', 'success')
    return redirect(url_for('phoi.detail', id=id))


@bp.route('/phoi/<int:id>/confirm', methods=['GET', 'POST'])
@login_required
def confirm(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền xác nhận phơi.', 'danger')
        return redirect(url_for('phoi.index'))

    phoi = Phoi.query.get_or_404(id)
    if phoi.status != 'submitted':
        flash('Chỉ có thể xác nhận phơi đã chốt.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    trips = [
        {'kind': 'outbound', 'label': 'Chuyến đi', 'customer': phoi.customer,
         'revenue_full': phoi.revenue_full, 'revenue_collected': phoi.revenue_collected,
         'manager_revenue_collected': phoi.manager_revenue_collected},
        *[
            {'kind': 'return', 'id': trip.id, 'label': f'Chuyến về #{trip.trip_order}',
             'customer': trip.customer, 'revenue_full': trip.revenue_full,
             'revenue_collected': trip.revenue_collected,
             'manager_revenue_collected': trip.manager_revenue_collected}
            for trip in phoi.return_trips.all()
        ],
    ]
    if request.method == 'GET':
        return render_template('phoi/confirm.html', phoi=phoi, trips=trips)

    try:
        for trip in trips:
            if trip['kind'] == 'outbound':
                status_name = 'outbound_collection_status'
                amount_name = 'outbound_manager_revenue_collected'
                target = phoi
            else:
                status_name = f"return_collection_status_{trip['id']}"
                amount_name = f"return_manager_revenue_collected_{trip['id']}"
                target = PhoiReturnTrip.query.get_or_404(trip['id'])
            status = request.form.get(status_name, 'unpaid')
            remaining = (target.revenue_full or Decimal('0')) - (target.revenue_collected or Decimal('0'))
            if status == 'unpaid':
                target.manager_revenue_collected = Decimal('0')
            elif status == 'full':
                target.manager_revenue_collected = remaining
            elif status == 'partial':
                target.manager_revenue_collected = _money(request.form.get(amount_name, 0))
            else:
                raise ValueError('Trạng thái thu tiền không hợp lệ.')

        _sync_confirmation_toll_fee(phoi)
        error = submission_error(phoi) or financial_confirmation_error(phoi)
        if error:
            raise ValueError(error)

        phoi.status = 'confirmed'
        phoi.confirmed_by_id = current_user.id
        phoi.confirmed_at = datetime.utcnow()
        update_truck_status(phoi.truck)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), 'danger')
        return redirect(url_for('phoi.confirm', id=id))

    flash(f'Đã xác nhận phơi {phoi.phoi_number}. Balance: {phoi.balance():,.0f} VNĐ', 'success')
    return redirect(url_for('phoi.detail', id=id))