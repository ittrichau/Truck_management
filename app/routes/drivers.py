from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from app import db
from app.models import User, Truck

bp = Blueprint('drivers', __name__)

@bp.route('/drivers')
@login_required
def index():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    drivers = User.query.filter_by(role='driver', is_active=True).order_by(User.full_name).all()
    return render_template('drivers/index.html', drivers=drivers)

@bp.route('/drivers/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    # Lấy danh sách xe chưa gán cho tài xế nào
    assigned_truck_ids = [u.current_truck_id for u in User.query.filter(
        User.role == 'driver',
        User.is_active == True,
        User.current_truck_id.isnot(None)
    ).all()]
    available_trucks = Truck.query.filter(
        Truck.is_active == True,
        ~Truck.id.in_(assigned_truck_ids) if assigned_truck_ids else True
    ).order_by(Truck.license_plate).all()

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        full_name = request.form.get('full_name', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        truck_id = request.form.get('current_truck_id')

        if not username or not full_name or not password:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks)

        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks)

        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks)

        driver = User(
            username=username,
            full_name=full_name,
            phone=phone,
            role='driver'
        )
        if truck_id:
            driver.current_truck_id = int(truck_id)
        driver.set_password(password)
        db.session.add(driver)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Xe này đã được gán cho tài xế khác. Vui lòng chọn xe khác.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks)
        flash(f'Đã thêm tài xế {full_name}.', 'success')
        return redirect(url_for('drivers.index'))

    return render_template('drivers/create.html', trucks=available_trucks)

@bp.route('/drivers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    driver = User.query.get_or_404(id)
    if driver.role != 'driver':
        flash('Không thể sửa người dùng này.', 'danger')
        return redirect(url_for('drivers.index'))

    # Lấy danh sách xe, bao gồm cả xe hiện tại của driver này
    assigned_truck_ids = [u.current_truck_id for u in User.query.filter(
        User.role == 'driver',
        User.is_active == True,
        User.current_truck_id.isnot(None),
        User.id != id
    ).all()]
    available_trucks = Truck.query.filter(
        Truck.is_active == True,
        ~Truck.id.in_(assigned_truck_ids) if assigned_truck_ids else True
    ).order_by(Truck.license_plate).all()

    if request.method == 'POST':
        driver.full_name = request.form.get('full_name', '').strip()
        driver.phone = request.form.get('phone', '').strip()

        truck_id = request.form.get('current_truck_id')
        if truck_id:
            driver.current_truck_id = int(truck_id)
        else:
            driver.current_truck_id = None

        new_password = request.form.get('password', '').strip()
        if new_password:
            confirm_password = request.form.get('confirm_password', '').strip()
            if new_password != confirm_password:
                flash('Mật khẩu xác nhận không khớp.', 'danger')
                return render_template('drivers/edit.html', driver=driver, trucks=available_trucks)
            driver.set_password(new_password)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Xe này đã được gán cho tài xế khác. Vui lòng chọn xe khác.', 'danger')
            return render_template('drivers/edit.html', driver=driver, trucks=available_trucks)
        flash(f'Đã cập nhật tài xế {driver.full_name}.', 'success')
        return redirect(url_for('drivers.index'))

    return render_template('drivers/edit.html', driver=driver, trucks=available_trucks)

@bp.route('/drivers/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    driver = User.query.get_or_404(id)
    if driver.role != 'driver':
        flash('Không thể xóa người dùng này.', 'danger')
        return redirect(url_for('drivers.index'))

    # Giải phóng xe nếu có
    driver.current_truck_id = None
    driver.is_active = False
    db.session.commit()
    flash(f'Đã xóa tài xế {driver.full_name}.', 'success')
    return redirect(url_for('drivers.index'))
