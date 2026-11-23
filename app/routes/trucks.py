from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import datetime, date
from app import db
from app.models import Truck, User, Phoi

from app.access import trucks_query, drivers_query, require_driver_truck, manager_id

bp = Blueprint('trucks', __name__)


def _parse_date(val):
    """Parse YYYY-MM-DD string to date object, return None if empty/invalid."""
    if val and val.strip():
        try:
            return datetime.strptime(val.strip(), '%Y-%m-%d').date()
        except ValueError:
            pass
    return None


def _document_expiries():
    legacy_fields = ('inspection_date', 'inspection_expiry_months', 'permit_date', 'permit_expiry_months')
    if any(field in request.form for field in legacy_fields):
        raise ValueError('Biểu mẫu đã thay đổi. Vui lòng tải lại trang và nhập ngày hết hạn theo giấy tờ.')
    values = {}
    for field, column, label in (
        ('inspection_expiry_date', 'inspection_expires_on', 'đăng kiểm'),
        ('permit_expiry_date', 'permit_expires_on', 'phù hiệu'),
        ('insurance_expiry_date', 'insurance_expiry_date', 'bảo hiểm'),
    ):
        if field not in request.form:
            continue  # Omitted edit fields preserve their current value.
        raw = request.form[field].strip()
        value = _parse_date(raw)
        if raw and (value is None or value.isoformat() != raw):
            raise ValueError(f'Ngày hết hạn {label} không hợp lệ.')
        values[column] = value
    return values


@bp.route('/trucks')
@login_required
def index():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    trucks = trucks_query().filter_by(is_active=True).order_by(Truck.license_plate).all()

    # Prepare data: current driver + active phoi status per truck
    truck_data = []
    for truck in trucks:
        # Find current driver assigned to this truck
        current_driver = User.query.filter_by(
            current_truck_id=truck.id,
            role='driver',
            is_active=True
        ).first()

        # Check if truck has any active phoi (draft or submitted = đang vận chuyển)
        active_phoi = Phoi.query.filter(
            Phoi.truck_id == truck.id,
            Phoi.status.in_(['draft', 'submitted'])
        ).first()

        truck_data.append({
            'truck': truck,
            'current_driver': current_driver,
            'has_active_phoi': active_phoi is not None
        })

    return render_template('trucks/index.html', truck_data=truck_data, today=date.today())


@bp.route('/trucks/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    if request.method == 'POST':
        try:
            expiry_values = _document_expiries()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return render_template('trucks/create.html')

        license_plate = request.form.get('license_plate').strip()
        if Truck.query.filter_by(license_plate=license_plate).first():
            flash('Biển số xe đã tồn tại.', 'danger')
            return render_template('trucks/create.html')

        truck = Truck(
            manager_id=manager_id(),
            license_plate=license_plate,
            brand=request.form.get('brand', '').strip(),
            capacity_ton=float(request.form.get('capacity_ton', 0) or 0),
            year=int(request.form.get('year', 0) or 0),
            fuel_rate=float(request.form.get('fuel_rate', 0) or 0),
            current_km=int(request.form.get('current_km', 0) or 0),
            **expiry_values,
            status=request.form.get('status', 'available'),
            notes=request.form.get('notes', '').strip()
        )
        db.session.add(truck)
        db.session.commit()
        flash(f'Đã thêm xe {license_plate}.', 'success')
        return redirect(url_for('trucks.index'))

    return render_template('trucks/create.html')


@bp.route('/trucks/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    truck = trucks_query().filter_by(id=id).first_or_404()

    # Lấy danh sách tài xế có thể gán: chưa gán xe + đang giữ xe này (để có thể đổi/chuyển)
    assigned_driver_ids = [u.id for u in User.query.filter(
        User.role == 'driver',
        User.is_active == True,
        User.current_truck_id.isnot(None),
        User.current_truck_id != truck.id
    ).all()]
    available_drivers = drivers_query().filter(
        User.role == 'driver',
        User.is_active == True,
        ~User.id.in_(assigned_driver_ids) if assigned_driver_ids else True
    ).order_by(User.full_name).all()

    # Tài xế hiện tại đang giữ xe này
    current_driver = User.query.filter_by(
        current_truck_id=truck.id,
        role='driver',
        is_active=True
    ).first()

    if request.method == 'POST':
        try:
            expiry_values = _document_expiries()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return render_template(
                'trucks/edit.html',
                truck=truck,
                available_drivers=available_drivers,
                current_driver=current_driver
            )

        truck.license_plate = request.form.get('license_plate', '').strip()
        truck.brand = request.form.get('brand', '').strip()
        truck.capacity_ton = float(request.form.get('capacity_ton', 0) or 0)
        truck.year = int(request.form.get('year', 0) or 0)
        truck.fuel_rate = float(request.form.get('fuel_rate', 0) or 0)
        truck.current_km = int(request.form.get('current_km', 0) or 0)
        for column, value in expiry_values.items():
            if getattr(truck, column) != value:
                setattr(truck, column, value)
                if column == 'inspection_expires_on':
                    truck.last_inspection_notified_at = None
                elif column == 'permit_expires_on':
                    truck.last_permit_notified_at = None
        truck.status = request.form.get('status', 'available')
        truck.notes = request.form.get('notes', '').strip()

        # Gán/chuyển tài xế
        driver_id = request.form.get('current_driver_id')
        old_driver = User.query.filter_by(current_truck_id=truck.id, role='driver', is_active=True).first()

        if old_driver:
            old_driver.current_truck_id = None

        if driver_id:
            new_driver = drivers_query().filter_by(id=int(driver_id), is_active=True).first_or_404()
            if new_driver and new_driver.role == 'driver':
                require_driver_truck(new_driver, truck)
                new_driver.current_truck_id = truck.id

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Có lỗi xảy ra khi gán tài xế. Vui lòng thử lại.', 'danger')
            return render_template(
                'trucks/edit.html',
                truck=truck,
                available_drivers=available_drivers,
                current_driver=current_driver
            )

        flash(f'Đã cập nhật xe {truck.license_plate}.', 'success')
        return redirect(url_for('trucks.index'))

    return render_template(
        'trucks/edit.html',
        truck=truck,
        available_drivers=available_drivers,
        current_driver=current_driver
    )


@bp.route('/trucks/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    truck = trucks_query().filter_by(id=id).first_or_404()
    truck.is_active = False
    db.session.commit()
    flash(f'Đã xóa xe {truck.license_plate}.', 'success')
    return redirect(url_for('trucks.index'))
