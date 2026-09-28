from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file
from flask_login import login_required, current_user
from app import db
from app.models import Phoi, PhoiAttachment, PhoiExpense, PhoiReturnTrip, FuelLog, Customer, Truck, User, generate_phoi_number
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
    if phoi.fuel_logs.count() == 0:
        return 'Phơi chưa được gắn lần đổ xăng nào. Vui lòng ghi nhận đổ xăng trước khi chốt.'
    if not phoi.km_start or not phoi.km_end or phoi.km_end < phoi.km_start:
        return 'Vui lòng nhập KM đầu và KM cuối hợp lệ trước khi chốt phơi.'
    required_attachments = {
        'km_start': 'ảnh đồng hồ KM đầu',
        'km_end': 'ảnh đồng hồ KM cuối',
        'weigh_ticket': 'ít nhất một ảnh phiếu cân',
    }
    for attachment_type, label in required_attachments.items():
        if phoi.attachment_count(attachment_type) == 0:
            return f'Phơi chưa có {label}. Vui lòng tải ảnh lên trước khi chốt.'
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
    customer_ids = request.form.getlist('return_trip_customer_id[]')
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

        customer_id = customer_ids[index] if index < len(customer_ids) else ''
        trip = PhoiReturnTrip(
            phoi_id=phoi.id,
            customer_id=int(customer_id) if customer_id else None,
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
        saved_keys = []
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

            phoi.km_start = truck.current_km
            phoi.km_end = int(request.form.get('km_end', 0) or 0)
            if phoi.km_end and phoi.km_end < phoi.km_start:
                raise ValueError('KM cuối không thể nhỏ hơn KM đầu.')
            phoi.calculate_km_total()
            phoi.cargo_weight_tons = float(request.form.get('cargo_weight_tons', 0) or 0) or None
            phoi.weigh_ticket_number = request.form.get('weigh_ticket_number', '').strip() or None

            phoi.revenue_full = float(request.form.get('revenue_full', 0) or 0)
            phoi.revenue_collected = float(request.form.get('revenue_collected', 0) or 0)

            # Phơi mới đang thực hiện; chuyến về và đổ xăng sẽ được thêm sau.
            phoi.status = 'draft'
            phoi.notes = request.form.get('notes', '').strip()

            db.session.add(phoi)
            db.session.flush()
            _sync_return_trips(phoi)

            for attachment_type, field_name, maximum_files in (
                ('km_start', 'km_start_images', 1),
                ('weigh_ticket', 'weigh_ticket_images', 5),
            ):
                files = [file for file in request.files.getlist(field_name) if file and file.filename]
                if len(files) > maximum_files:
                    raise ValueError(
                        'Ảnh đồng hồ KM đầu chỉ được tải 1 ảnh.'
                        if attachment_type == 'km_start'
                        else 'Ảnh phiếu cân chỉ được tải tối đa 5 ảnh khi tạo phơi.'
                    )
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

            if phoi.km_end:
                truck.current_km = max(truck.current_km, phoi.km_end)
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
    if phoi.status != 'draft' or not can_manage_phoi(current_user, phoi):
        flash('Chỉ có thể tải chứng từ cho phơi đang thực hiện của bạn.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    attachment_type = request.form.get('attachment_type', '')
    if attachment_type not in PhoiAttachment.TYPES:
        flash('Loại chứng từ không hợp lệ.', 'danger')
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
                phoi_id=phoi.id, attachment_type=attachment_type,
                notes=request.form.get('notes', '').strip() or None,
                uploaded_by_id=current_user.id, **metadata
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
    if phoi.status != 'draft' or not can_manage_phoi(current_user, phoi):
        flash('Chỉ có thể xóa chứng từ của phơi đang thực hiện.', 'danger')
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

    if phoi.status != 'draft':
        flash('Chỉ có thể sửa phơi đang thực hiện. Phơi đã chốt hoặc xác nhận không thể chỉnh sửa.', 'warning')
        return redirect(url_for('phoi.detail', id=id))
    if not can_manage_phoi(current_user, phoi):
        flash('Bạn không có quyền sửa phơi này.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    trucks, drivers, driver_by_truck_id = _active_phoi_options()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        saved_keys = []
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
            if phoi.km_end and phoi.km_end < phoi.km_start:
                raise ValueError('KM cuối không thể nhỏ hơn KM đầu.')
            phoi.calculate_km_total()
            phoi.cargo_weight_tons = float(request.form.get('cargo_weight_tons', 0) or 0) or None
            phoi.weigh_ticket_number = request.form.get('weigh_ticket_number', '').strip() or None
            phoi.revenue_full = float(request.form.get('revenue_full', 0) or 0)
            phoi.revenue_collected = float(request.form.get('revenue_collected', 0) or 0)
            phoi.notes = request.form.get('notes', '').strip()

            if current_user.is_manager_or_admin():
                phoi.driver_wage = float(request.form.get('driver_wage', 0) or 0)

            _sync_return_trips(phoi)
            _sync_standard_expenses(phoi)
            repairs = _sync_repair_expenses(phoi)
            _save_repair_receipts(phoi, repairs, saved_keys)

            if phoi.km_end:
                truck.current_km = max(truck.current_km, phoi.km_end)
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