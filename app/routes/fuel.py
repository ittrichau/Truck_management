from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, send_file
from flask_login import login_required, current_user
from app import db
from app.models import FuelLog, FuelPrice, FuelReceipt, Truck, Phoi
from app.phoi_attachments import save_phoi_attachment, delete_attachment_file, attachment_path
from datetime import datetime, date, timedelta

bp = Blueprint('fuel', __name__)


@bp.route('/fuel')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    query = FuelLog.query.order_by(FuelLog.refuel_date.desc())
    logs = query.paginate(page=page, per_page=20, error_out=False)

    trucks = Truck.query.filter_by(is_active=True).all()

    truck_stats = {}
    for t in trucks:
        trip_count = Phoi.query.filter_by(truck_id=t.id, status='confirmed').count()
        last_fuel = FuelLog.query.filter_by(truck_id=t.id).order_by(FuelLog.refuel_date.desc()).first()
        days_since = None
        if last_fuel:
            days_since = (date.today() - last_fuel.refuel_date).days
        truck_stats[t.id] = {
            'trip_count': trip_count,
            'days_since': days_since,
            'needs_refuel': trip_count % 2 == 0 and trip_count > 0 and (not last_fuel or days_since > 7)
        }

    return render_template('fuel/index.html', logs=logs, trucks=trucks, truck_stats=truck_stats)


def _get_active_price_or_none(for_date=None):
    """Helper: lấy giá đang hiệu lực, hoặc None nếu không có"""
    dt = datetime.combine(for_date, datetime.min.time()) if for_date else datetime.utcnow()
    return FuelPrice.get_active_price(dt)


@bp.route('/fuel/create', methods=['GET', 'POST'])
@login_required
def create():
    trucks = Truck.query.filter_by(is_active=True).all()
    phoi_query = Phoi.query.filter(Phoi.status.in_(['draft', 'submitted']))
    if current_user.is_driver():
        phoi_query = phoi_query.filter_by(driver_id=current_user.id)
    phois = phoi_query.order_by(Phoi.created_at.desc()).all()

    selected_phoi_id = request.args.get('phoi_id', type=int)
    selected_truck_id = request.args.get('truck_id', type=int)
    selected_phoi = Phoi.query.get(selected_phoi_id) if selected_phoi_id else None
    if selected_phoi:
        if selected_phoi.status == 'confirmed' or (current_user.is_driver() and selected_phoi.driver_id != current_user.id):
            flash('Bạn không có quyền ghi nhận đổ xăng cho phơi này.', 'danger')
            return redirect(url_for('phoi.index'))
        selected_truck_id = selected_phoi.truck_id

    if request.method == 'POST':
        try:
            liters = float(request.form.get('liters', 0))
            if liters <= 0:
                raise ValueError('Số lít phải lớn hơn 0.')
            paid_by = request.form.get('paid_by', 'owner')
            if paid_by not in ('owner', 'driver'):
                raise ValueError('Hình thức thanh toán không hợp lệ.')
            is_home_station = request.form.get('is_home_station') == '1'
            receipt_files = [file for file in request.files.getlist('receipts') if file and file.filename]
            if not receipt_files:
                raise ValueError('Mọi lần đổ xăng phải tải lên ít nhất một ảnh chứng từ.')
            if len(receipt_files) > 5:
                raise ValueError('Chỉ được tải tối đa 5 ảnh chứng từ mỗi lần đổ xăng.')
            refuel_date_str = request.form.get('refuel_date', '')
            refuel_date = datetime.strptime(refuel_date_str, '%Y-%m-%d').date() if refuel_date_str else date.today()

            # Tự động lấy giá xăng từ bảng FuelPrice
            fuel_price = _get_active_price_or_none(refuel_date)
            if fuel_price:
                price = float(fuel_price.price_per_liter)
            else:
                price = float(request.form.get('price_per_liter', 0))
                if price <= 0:
                    flash('Chưa có giá xăng cho ngày này. Vui lòng nhập giá thủ công.', 'warning')

            truck_id = int(request.form.get('truck_id', 0))

            # Kiểm tra chạy giùm: tài xế đổ xăng cho xe không phải xe mặc định
            is_substitute = False
            if current_user.is_driver() and current_user.current_truck_id:
                if truck_id != current_user.current_truck_id:
                    is_substitute = True

            log = FuelLog(
                truck_id=truck_id,
                liters=liters,
                price_per_liter=price,
                total_cost=liters * price,
                paid_by=paid_by,
                is_home_station=is_home_station,
                refuel_date=refuel_date,
                is_substitute=is_substitute,
                notes=request.form.get('notes', '').strip(),
                created_by_id=current_user.id
            )

            # Mỗi lần đổ xăng chỉ được tính cho một phơi đang thực hiện cùng xe.
            selected_phoi_id = request.form.get('phoi_id', type=int)
            selected_phoi_record = Phoi.query.get(selected_phoi_id) if selected_phoi_id else None
            if not selected_phoi_record or selected_phoi_record.status not in ['draft', 'submitted']:
                flash('Phải chọn đúng một phơi đang thực hiện để ghi nhận lần đổ xăng.', 'danger')
                return render_template('fuel/create.html', trucks=trucks, phois=phois,
                                       current_price=_get_active_price_or_none(),
                                       selected_truck_id=truck_id, selected_phoi_id=selected_phoi_id,
                                       is_home_station=is_home_station)
            if current_user.is_driver() and selected_phoi_record.driver_id != current_user.id:
                flash('Tài xế chỉ được gắn đổ xăng vào phơi của mình.', 'danger')
                return render_template('fuel/create.html', trucks=trucks, phois=phois,
                                       current_price=_get_active_price_or_none(),
                                       selected_truck_id=truck_id, selected_phoi_id=selected_phoi_id,
                                       is_home_station=is_home_station)
            if selected_phoi_record.truck_id != truck_id:
                flash(f'Phơi {selected_phoi_record.phoi_number} không thuộc xe đã chọn. Vui lòng chọn phơi của cùng xe.', 'danger')
                return render_template('fuel/create.html', trucks=trucks, phois=phois,
                                       current_price=_get_active_price_or_none(),
                                       selected_truck_id=truck_id, selected_phoi_id=selected_phoi_id,
                                       is_home_station=is_home_station)
            log.phois.append(selected_phoi_record)

            db.session.add(log)
            db.session.flush()
            saved_keys = []
            try:
                for file in receipt_files:
                    metadata = save_phoi_attachment(file, log.id)
                    saved_keys.append(metadata['storage_key'])
                    image_type = 'liters' if is_home_station else 'receipt'
                    db.session.add(FuelReceipt(
                        fuel_log_id=log.id, uploaded_by_id=current_user.id,
                        image_type=image_type, **metadata
                    ))
                db.session.commit()
            except Exception:
                for storage_key in saved_keys:
                    delete_attachment_file(storage_key)
                raise
            flash(f'Đã ghi nhận đổ {liters} lít xăng (giá {price:,.0f}đ/lít).', 'success')
            return_to_phoi_id = request.form.get('return_to_phoi_id', type=int)
            if return_to_phoi_id:
                return redirect(url_for('phoi.detail', id=return_to_phoi_id))
            return redirect(url_for('fuel.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')

    # GET: hiển thị giá xăng mặc định nếu có
    return render_template('fuel/create.html', trucks=trucks, phois=phois,
                           current_price=_get_active_price_or_none(),
                           selected_phoi_id=selected_phoi_id,
                           selected_truck_id=selected_truck_id)


@bp.route('/fuel/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    log = FuelLog.query.get_or_404(id)
    linked_phois = log.phois.all()
    if current_user.is_driver() and (
        log.created_by_id != current_user.id
        or any(phoi.driver_id != current_user.id for phoi in linked_phois)
    ):
        flash('Bạn không có quyền sửa lần đổ xăng này.', 'danger')
        return redirect(url_for('fuel.index'))
    has_confirmed_link = any(phoi.status == 'confirmed' for phoi in linked_phois)
    if has_confirmed_link and not current_user.is_admin():
        flash('Không thể sửa lần đổ xăng đã gắn với phơi được xác nhận.', 'warning')
        return redirect(url_for('fuel.index'))
    if has_confirmed_link and len(linked_phois) != 1:
        flash('Không thể sửa lần đổ xăng đang được nhiều phơi sử dụng.', 'warning')
        return redirect(url_for('fuel.index'))

    if request.method == 'POST':
        try:
            liters = float(request.form.get('liters', 0))
            if liters <= 0:
                raise ValueError('Số lít phải lớn hơn 0.')
            is_home_station = request.form.get('is_home_station') == '1'
            existing_receipts = log.receipts.all()
            receipt_files = [file for file in request.files.getlist('receipts') if file and file.filename]
            if not existing_receipts and not receipt_files:
                raise ValueError('Cần có ít nhất một ảnh chứng từ cho lần đổ xăng này.')
            if len(receipt_files) + len(existing_receipts) > 5:
                raise ValueError('Chỉ được lưu tối đa 5 ảnh chứng từ mỗi lần đổ xăng.')
            refuel_date_str = request.form.get('refuel_date', '')
            if not refuel_date_str:
                raise ValueError('Vui lòng chọn ngày đổ xăng.')
            log.liters = liters
            log.is_home_station = is_home_station
            log.refuel_date = datetime.strptime(refuel_date_str, '%Y-%m-%d').date()
            log.total_cost = liters * log.price_per_liter
            saved_keys = []
            try:
                image_type = 'liters' if is_home_station else 'receipt'
                for receipt in existing_receipts:
                    receipt.image_type = image_type
                for file in receipt_files:
                    metadata = save_phoi_attachment(file, log.id)
                    saved_keys.append(metadata['storage_key'])
                    db.session.add(FuelReceipt(
                        fuel_log_id=log.id, uploaded_by_id=current_user.id,
                        image_type=image_type, **metadata
                    ))
                db.session.commit()
            except Exception:
                db.session.rollback()
                for storage_key in saved_keys:
                    delete_attachment_file(storage_key)
                raise
            flash('Đã cập nhật số lít và ngày đổ xăng.', 'success')
            if len(linked_phois) == 1:
                return redirect(url_for('phoi.detail', id=linked_phois[0].id))
            return redirect(url_for('fuel.index'))
        except (TypeError, ValueError) as exc:
            db.session.rollback()
            flash(f'Lỗi: {str(exc)}', 'danger')

    return render_template('fuel/edit.html', log=log, linked_phois=linked_phois)

@bp.route('/fuel/<int:id>/receipts/<int:receipt_id>')
@login_required
def view_receipt(id, receipt_id):
    log = FuelLog.query.get_or_404(id)
    if current_user.is_driver() and log.created_by_id != current_user.id:
        flash('Bạn không có quyền xem hóa đơn này.', 'danger')
        return redirect(url_for('fuel.index'))
    receipt = FuelReceipt.query.filter_by(id=receipt_id, fuel_log_id=log.id).first_or_404()
    try:
        path = attachment_path(receipt.storage_key)
        if not path.is_file():
            raise FileNotFoundError
        return send_file(path, mimetype=receipt.mime_type, conditional=True)
    except (FileNotFoundError, ValueError):
        flash('Không tìm thấy ảnh hóa đơn.', 'warning')
        return redirect(url_for('fuel.index'))

@bp.route('/fuel/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    log = FuelLog.query.get_or_404(id)
    linked_phois = log.phois.all()
    if current_user.is_driver() and (
        log.created_by_id != current_user.id
        or any(phoi.driver_id != current_user.id for phoi in linked_phois)
    ):
        flash('Bạn không có quyền xóa lần đổ xăng này.', 'danger')
        return redirect(url_for('fuel.index'))
    has_confirmed_link = any(phoi.status == 'confirmed' for phoi in linked_phois)
    if has_confirmed_link and not current_user.is_admin():
        flash('Không thể xóa lần đổ xăng đã gắn với phơi được xác nhận.', 'danger')
        return redirect(url_for('fuel.index'))
    if has_confirmed_link and len(linked_phois) != 1:
        flash('Không thể xóa lần đổ xăng đang được nhiều phơi sử dụng.', 'danger')
        return redirect(url_for('fuel.index'))
    receipt_keys = [receipt.storage_key for receipt in log.receipts.all()]
    db.session.delete(log)
    db.session.commit()
    for storage_key in receipt_keys:
        delete_attachment_file(storage_key)
    flash('Đã xóa bản ghi đổ xăng. Nếu đây là lần xăng cuối, hãy thêm lại trước khi xác nhận phơi.', 'success')
    if len(linked_phois) == 1:
        return redirect(url_for('phoi.detail', id=linked_phois[0].id))
    return redirect(url_for('fuel.index'))


# ============ Quản lý giá xăng (admin) ============
@bp.route('/fuel/prices')
@login_required
def price_list():
    if not current_user.is_manager_or_admin():
        flash('Không có quyền.', 'danger')
        return redirect(url_for('fuel.index'))
    prices = FuelPrice.query.order_by(FuelPrice.effective_from.desc()).all()
    return render_template('fuel/prices.html', prices=prices)


def _has_price_on_effective_days(effective_from, effective_to, exclude_id=None):
    query = FuelPrice.query
    if exclude_id is not None:
        query = query.filter(FuelPrice.id != exclude_id)

    day_start = datetime.combine(effective_from.date(), datetime.min.time())
    next_day_start = day_start + timedelta(days=1)
    return query.filter(
        FuelPrice.effective_from >= day_start,
        FuelPrice.effective_from < next_day_start,
    ).first() is not None


@bp.route('/fuel/prices/create', methods=['GET', 'POST'])
@login_required
def create_price():
    if not current_user.is_admin():
        flash('Chỉ admin mới được tạo giá xăng.', 'danger')
        return redirect(url_for('fuel.price_list'))
    if request.method == 'POST':
        try:
            # Parse datetime từ form (định dạng: YYYY-MM-DDTHH:MM)
            effective_from_str = request.form.get('effective_from', '')
            # Mặc định 3:00 PM (15:00) nếu không nhập giờ
            now = datetime.now()
            default_from = now.replace(hour=15, minute=0, second=0, microsecond=0)
            effective_from = datetime.strptime(effective_from_str, '%Y-%m-%dT%H:%M') if effective_from_str else default_from

            effective_to_str = request.form.get('effective_to', '').strip()
            effective_to = datetime.strptime(effective_to_str, '%Y-%m-%dT%H:%M') if effective_to_str else None
            if effective_to and effective_to <= effective_from:
                raise ValueError('Thời điểm kết thúc phải sau thời điểm bắt đầu.')
            if _has_price_on_effective_days(effective_from, effective_to):
                raise ValueError('Ngày bắt đầu hiệu lực đã có bảng giá khác. Mỗi ngày chỉ được có một giá xăng.')

            # Tìm giá đang hiệu lực (có effective_to = NULL) và tự động đóng lại
            active_price = FuelPrice.get_active_price(effective_from)
            if active_price and active_price.effective_to is None:
                # Đóng giá cũ: kết thúc ngay trước thời điểm effective_from của giá mới
                active_price.effective_to = effective_from - timedelta(seconds=1)
                current_app.logger.info(f"[fuel] Auto-closed price #{active_price.id} to {active_price.effective_to}")

            fp = FuelPrice(
                price_per_liter=float(request.form.get('price_per_liter', 0)),
                effective_from=effective_from,
                effective_to=effective_to,
                notes=request.form.get('notes', '').strip(),
                created_by_id=current_user.id
            )
            db.session.add(fp)
            db.session.commit()

            if effective_to:
                flash(f'Đã thêm giá xăng {fp.price_per_liter:,.0f}đ/lít ({fp.effective_from.strftime("%d/%m/%Y %H:%M")} → {fp.effective_to.strftime("%d/%m/%Y %H:%M")}).', 'success')
            else:
                flash(f'Đã thêm giá xăng {fp.price_per_liter:,.0f}đ/lít (từ {fp.effective_from.strftime("%d/%m/%Y %H:%M")}).', 'success')
            return redirect(url_for('fuel.price_list'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')
    # Mặc định 3:00 PM (15:00) hôm nay cho datetime-local input
    now = datetime.now()
    today_15h = now.replace(hour=15, minute=0, second=0, microsecond=0).strftime('%Y-%m-%dT%H:%M')
    return render_template('fuel/price_form.html', price=None, today_15h=today_15h)


@bp.route('/fuel/prices/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit_price(id):
    if not current_user.is_admin():
        flash('Chỉ admin mới được sửa giá xăng.', 'danger')
        return redirect(url_for('fuel.price_list'))

    fp = FuelPrice.query.get_or_404(id)
    if request.method == 'POST':
        try:
            price_per_liter = float(request.form.get('price_per_liter', '').replace(',', '').strip())
            if price_per_liter <= 0:
                raise ValueError('Giá xăng phải lớn hơn 0.')

            effective_from_str = request.form.get('effective_from', '').strip()
            if not effective_from_str:
                raise ValueError('Vui lòng chọn thời điểm bắt đầu hiệu lực.')
            effective_from = datetime.strptime(effective_from_str, '%Y-%m-%dT%H:%M')

            effective_to_str = request.form.get('effective_to', '').strip()
            effective_to = datetime.strptime(effective_to_str, '%Y-%m-%dT%H:%M') if effective_to_str else None
            if effective_to and effective_to <= effective_from:
                raise ValueError('Thời điểm kết thúc phải sau thời điểm bắt đầu.')
            if _has_price_on_effective_days(effective_from, effective_to, exclude_id=fp.id):
                raise ValueError('Ngày bắt đầu hiệu lực đã có bảng giá khác. Mỗi ngày chỉ được có một giá xăng.')

            fp.price_per_liter = price_per_liter
            fp.effective_from = effective_from
            fp.effective_to = effective_to
            fp.notes = request.form.get('notes', '').strip()
            db.session.commit()
            flash('Đã cập nhật bảng giá xăng. Các lần đổ xăng đã ghi nhận không thay đổi.', 'success')
            return redirect(url_for('fuel.price_list'))
        except (TypeError, ValueError) as exc:
            db.session.rollback()
            flash(f'Lỗi: {str(exc)}', 'danger')

    return render_template(
        'fuel/price_form.html',
        price=fp,
        today_15h=fp.effective_from.strftime('%Y-%m-%dT%H:%M'),
    )


@bp.route('/fuel/prices/<int:id>/delete', methods=['POST'])
@login_required
def delete_price(id):
    if not current_user.is_admin():
        flash('Chỉ admin mới được xóa giá xăng.', 'danger')
        return redirect(url_for('fuel.price_list'))

    fp = FuelPrice.query.get_or_404(id)
    db.session.delete(fp)
    db.session.commit()
    flash('Đã xóa bảng giá xăng. Các lần đổ xăng đã ghi nhận không thay đổi.', 'success')
    return redirect(url_for('fuel.price_list'))


@bp.route('/fuel/prices/<int:id>/toggle', methods=['POST'])
@login_required
def toggle_price(id):
    if not current_user.is_admin():
        flash('Chỉ admin.', 'danger')
        return redirect(url_for('fuel.price_list'))
    fp = FuelPrice.query.get_or_404(id)
    fp.is_active = not fp.is_active
    db.session.commit()
    flash(f'Đã {"kích hoạt" if fp.is_active else "vô hiệu hóa"} giá xăng.', 'success')
    return redirect(url_for('fuel.price_list'))