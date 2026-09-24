from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Phoi, PhoiExpense, PhoiReturnTrip, FuelLog, Customer, Truck, User, generate_phoi_number
from datetime import datetime, date

bp = Blueprint('phoi', __name__)


def can_manage_phoi(user, phoi):
    return user.is_manager_or_admin() or (user.is_driver() and phoi.driver_id == user.id)


def submission_error(phoi):
    if phoi.return_trips.count() == 0:
        return 'Phơi chưa có chuyến về. Vui lòng thêm ít nhất một chuyến về trước khi chốt.'
    if phoi.fuel_logs.count() == 0:
        return 'Phơi chưa được gắn lần đổ xăng nào. Vui lòng ghi nhận đổ xăng trước khi chốt.'
    return None


def update_truck_status(truck):
    if not truck:
        return
    has_active_phoi = Phoi.query.filter(
        Phoi.truck_id == truck.id,
        Phoi.status.in_(['draft', 'submitted'])
    ).count() > 0
    truck.status = 'in_trip' if has_active_phoi else 'available'



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


def _sync_return_trips(phoi):
    """Lưu các chuyến về từ biểu mẫu; một phơi có thể có nhiều chuyến về."""
    PhoiReturnTrip.query.filter_by(phoi_id=phoi.id).delete()

    dates = request.form.getlist('return_trip_date[]')
    origins = request.form.getlist('return_trip_origin[]')
    destinations = request.form.getlist('return_trip_destination[]')
    cargoes = request.form.getlist('return_trip_cargo[]')
    km_starts = request.form.getlist('return_trip_km_start[]')
    km_ends = request.form.getlist('return_trip_km_end[]')
    revenues = request.form.getlist('return_trip_revenue_full[]')
    collecteds = request.form.getlist('return_trip_revenue_collected[]')
    notes = request.form.getlist('return_trip_notes[]')

    for index, origin in enumerate(origins):
        origin = origin.strip()
        destination = destinations[index].strip() if index < len(destinations) else ''
        if not origin and not destination:
            continue
        if not origin or not destination:
            raise ValueError(f'Chuyến về #{index + 1} phải có đủ điểm đi và điểm đến.')

        trip = PhoiReturnTrip(
            phoi_id=phoi.id,
            trip_order=index + 1,
            return_date=datetime.strptime(dates[index], '%Y-%m-%d').date() if index < len(dates) and dates[index] else None,
            origin=origin,
            destination=destination,
            cargo_description=cargoes[index].strip() if index < len(cargoes) else '',
            km_start=int(km_starts[index] or 0) if index < len(km_starts) else 0,
            km_end=int(km_ends[index] or 0) if index < len(km_ends) else 0,
            revenue_full=float(revenues[index] or 0) if index < len(revenues) else 0,
            revenue_collected=float(collecteds[index] or 0) if index < len(collecteds) else 0,
            notes=notes[index].strip() if index < len(notes) else ''
        )
        trip.calculate_km_total()
        db.session.add(trip)


@bp.route('/')
@bp.route('/phoi')
@login_required
def index():
    """Danh sách phơi – driver chỉ thấy của mình, manager/admin thấy tất cả"""
    page = request.args.get('page', 1, type=int)

    if current_user.is_manager_or_admin():
        query = Phoi.query.order_by(Phoi.created_at.desc())
    else:
        query = Phoi.query.filter_by(driver_id=current_user.id).order_by(Phoi.created_at.desc())

    phois = query.paginate(page=page, per_page=20, error_out=False)

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

    return render_template('phoi/index.html', phois=phois, balances=balances, expiry_warnings=warnings)


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
        try:
            driver, truck, is_substitute = _selected_driver_and_truck()
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

            phoi.km_start = int(request.form.get('km_start', 0) or 0)
            phoi.km_end = int(request.form.get('km_end', 0) or 0)
            phoi.calculate_km_total()

            phoi.revenue_full = float(request.form.get('revenue_full', 0) or 0)
            phoi.revenue_collected = float(request.form.get('revenue_collected', 0) or 0)

            # Phơi mới đang thực hiện; chuyến về và đổ xăng sẽ được thêm sau.
            phoi.status = 'draft'
            phoi.notes = request.form.get('notes', '').strip()

            db.session.add(phoi)
            db.session.flush()
            _sync_return_trips(phoi)

            expense_categories = [
                ('porter_fee', 'Bồi dưỡng bốc vác'),
                ('toll_fee', 'Phí đường'),
                ('repair', 'Sửa xe'),
                ('other', 'Chi phí khác'),
            ]
            for cat_key, cat_label in expense_categories:
                amount = float(request.form.get(f'expense_{cat_key}', 0) or 0)
                if amount > 0:
                    exp = PhoiExpense(
                        phoi_id=phoi.id,
                        category=cat_key,
                        description=cat_label,
                        amount=amount
                    )
                    db.session.add(exp)

            truck.current_km = max(truck.current_km, phoi.km_end)
            truck.status = 'in_trip'

            db.session.commit()
            flash(f'Đã tạo phơi {phoi.phoi_number}. Phơi đang thực hiện, hãy thêm chuyến về và lần đổ xăng trước khi chốt.', 'success')
            return redirect(url_for('phoi.index'))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            flash(f'Lỗi khi tạo phơi: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi tạo phơi: {str(e)}', 'danger')

    return render_template(
        'phoi/create.html',
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

    if phoi.status != 'draft':
        flash('Chỉ có thể sửa phơi đang thực hiện. Phơi đã chốt hoặc xác nhận không thể chỉnh sửa.', 'warning')
        return redirect(url_for('phoi.detail', id=id))
    if not can_manage_phoi(current_user, phoi):
        flash('Bạn không có quyền sửa phơi này.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    trucks, drivers, driver_by_truck_id = _active_phoi_options()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        try:
            old_truck = phoi.truck
            driver, truck, is_substitute = _selected_driver_and_truck()
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
            phoi.km_start = int(request.form.get('km_start', 0) or 0)
            phoi.km_end = int(request.form.get('km_end', 0) or 0)
            phoi.calculate_km_total()
            phoi.revenue_full = float(request.form.get('revenue_full', 0) or 0)
            phoi.revenue_collected = float(request.form.get('revenue_collected', 0) or 0)
            phoi.notes = request.form.get('notes', '').strip()

            if current_user.is_manager_or_admin():
                phoi.driver_wage = float(request.form.get('driver_wage', 0) or 0)

            _sync_return_trips(phoi)
            PhoiExpense.query.filter_by(phoi_id=phoi.id).delete()
            expense_categories = [
                ('porter_fee', 'Bồi dưỡng bốc vác'),
                ('toll_fee', 'Phí đường'),
                ('repair', 'Sửa xe'),
                ('other', 'Chi phí khác'),
            ]
            for cat_key, cat_label in expense_categories:
                amount = float(request.form.get(f'expense_{cat_key}', 0) or 0)
                if amount > 0:
                    exp = PhoiExpense(phoi_id=phoi.id, category=cat_key, description=cat_label, amount=amount)
                    db.session.add(exp)

            truck.current_km = max(truck.current_km, phoi.km_end)
            update_truck_status(old_truck)
            update_truck_status(truck)
            db.session.commit()
            flash(f'Đã cập nhật phơi {phoi.phoi_number}.', 'success')
            return redirect(url_for('phoi.detail', id=id))

        except (ValueError, TypeError) as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')

    return render_template(
        'phoi/edit.html',
        phoi=phoi,
        trucks=trucks,
        customers=customers,
        drivers=drivers,
        driver_by_truck_id=driver_by_truck_id
    )


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


@bp.route('/phoi/<int:id>/confirm', methods=['POST'])
@login_required
def confirm(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền xác nhận phơi.', 'danger')
        return redirect(url_for('phoi.index'))

    phoi = Phoi.query.get_or_404(id)
    if phoi.status != 'submitted':
        flash('Chỉ có thể xác nhận phơi đã chốt.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    error = submission_error(phoi)
    if error:
        flash(error, 'danger')
        return redirect(url_for('phoi.detail', id=id))

    phoi.status = 'confirmed'
    phoi.confirmed_by_id = current_user.id
    phoi.confirmed_at = datetime.utcnow()
    update_truck_status(phoi.truck)
    db.session.commit()

    flash(f'Đã xác nhận phơi {phoi.phoi_number}. Balance: {phoi.balance():,.0f} VNĐ', 'success')
    return redirect(url_for('phoi.detail', id=id))