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

    is_admin = current_user.is_admin()
    if is_admin:
        # Admin thấy cả tài xế và quản lý
        drivers = User.query.filter(User.role.in_(['driver', 'manager']), User.is_active == True).order_by(User.full_name).all()
    else:
        # Manager chỉ thấy tài xế
        drivers = User.query.filter_by(role='driver', is_active=True).order_by(User.full_name).all()
    return render_template('drivers/index.html', drivers=drivers, is_admin=is_admin)

@bp.route('/drivers/create', methods=['GET', 'POST'])
@login_required
def create():
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    is_admin = current_user.is_admin()

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

        # Admin có thể chọn role, manager chỉ tạo driver
        if is_admin:
            role = request.form.get('role', 'driver')
            if role not in ('driver', 'manager'):
                flash('Vai trò không hợp lệ.', 'danger')
                return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)
        else:
            role = 'driver'

        if not username or not full_name or not password:
            flash('Vui lòng điền đầy đủ thông tin bắt buộc.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)

        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)

        if password != confirm_password:
            flash('Mật khẩu xác nhận không khớp.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)

        driver = User(
            username=username,
            full_name=full_name,
            phone=phone,
            role=role
        )
        if role == 'driver' and truck_id:
            driver.current_truck_id = int(truck_id)
        driver.set_password(password)
        db.session.add(driver)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Xe này đã được gán cho tài xế khác. Vui lòng chọn xe khác.', 'danger')
            return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)

        role_label = 'quản lý' if role == 'manager' else 'tài xế'
        flash(f'Đã thêm {role_label} {full_name}.', 'success')
        return redirect(url_for('drivers.index'))

    return render_template('drivers/create.html', trucks=available_trucks, is_admin=is_admin)

@bp.route('/drivers/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def edit(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    is_admin = current_user.is_admin()

    user = User.query.get_or_404(id)

    if not is_admin and user.role != 'driver':
        flash('Không thể sửa người dùng này.', 'danger')
        return redirect(url_for('drivers.index'))

    # Không cho phép sửa admin (chính mình hoặc admin khác) qua page này
    if user.role == 'admin':
        flash('Không thể sửa tài khoản admin tại đây.', 'danger')
        return redirect(url_for('drivers.index'))

    # Lấy danh sách xe, bao gồm cả xe hiện tại của người này (nếu là driver)
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
        user.full_name = request.form.get('full_name', '').strip()
        user.phone = request.form.get('phone', '').strip()

        # Admin có thể đổi role
        if is_admin:
            new_role = request.form.get('role', user.role)
            if new_role in ('driver', 'manager'):
                user.role = new_role
                # Nếu đổi thành manager, clear xe mặc định
                if new_role == 'manager':
                    user.current_truck_id = None

        # Chỉ cho phép gán xe nếu user là driver
        if user.role == 'driver':
            truck_id = request.form.get('current_truck_id')
            if truck_id:
                user.current_truck_id = int(truck_id)
            else:
                user.current_truck_id = None
        else:
            user.current_truck_id = None

        new_password = request.form.get('password', '').strip()
        if new_password:
            confirm_password = request.form.get('confirm_password', '').strip()
            if new_password != confirm_password:
                flash('Mật khẩu xác nhận không khớp.', 'danger')
                return render_template('drivers/edit.html', driver=user, trucks=available_trucks, is_admin=is_admin)
            user.set_password(new_password)

        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash('Xe này đã được gán cho tài xế khác. Vui lòng chọn xe khác.', 'danger')
            return render_template('drivers/edit.html', driver=user, trucks=available_trucks, is_admin=is_admin)

        role_label = 'quản lý' if user.role == 'manager' else 'tài xế'
        flash(f'Đã cập nhật {role_label} {user.full_name}.', 'success')
        return redirect(url_for('drivers.index'))

    return render_template('drivers/edit.html', driver=user, trucks=available_trucks, is_admin=is_admin)

@bp.route('/drivers/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    is_admin = current_user.is_admin()
    user = User.query.get_or_404(id)

    # Manager chỉ xóa được driver
    if not is_admin and user.role != 'driver':
        flash('Không thể xóa người dùng này.', 'danger')
        return redirect(url_for('drivers.index'))

    # Không cho xóa admin
    if user.role == 'admin':
        flash('Không thể xóa tài khoản admin.', 'danger')
        return redirect(url_for('drivers.index'))

    # Giải phóng xe nếu có
    user.current_truck_id = None
    user.is_active = False
    db.session.commit()

    role_label = 'quản lý' if user.role == 'manager' else 'tài xế'
    flash(f'Đã xóa {role_label} {user.full_name}.', 'success')
    return redirect(url_for('drivers.index'))
