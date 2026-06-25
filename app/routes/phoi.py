from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import Phoi, PhoiExpense, FuelLog, Customer, Truck, User, generate_phoi_number
from datetime import datetime, date

bp = Blueprint('phoi', __name__)


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

    return render_template('phoi/index.html', phois=phois, balances=balances)


@bp.route('/phoi/create', methods=['GET', 'POST'])
@login_required
def create():
    """Tài xế tạo phơi – giao diện tối ưu mobile"""
    if not current_user.is_driver():
        flash('Chỉ tài xế mới có thể tạo phơi.', 'danger')
        return redirect(url_for('phoi.index'))

    trucks = Truck.query.filter_by(is_active=True, status='available').all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        try:
            phoi = Phoi()
            phoi.phoi_number = generate_phoi_number()
            phoi.driver_id = current_user.id
            phoi.created_by_id = current_user.id
            phoi.truck_id = int(request.form.get('truck_id', 0))
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

            phoi.status = 'submitted'
            phoi.notes = request.form.get('notes', '').strip()

            db.session.add(phoi)
            db.session.flush()

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

            truck = Truck.query.get(phoi.truck_id)
            if truck:
                truck.current_km = max(truck.current_km, phoi.km_end)
                truck.status = 'available'

            db.session.commit()
            flash(f'Đã tạo phơi {phoi.phoi_number} thành công!', 'success')
            return redirect(url_for('phoi.index'))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi khi tạo phơi: {str(e)}', 'danger')

    return render_template('phoi/create.html', trucks=trucks, customers=customers)


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

    can_edit = current_user.is_manager_or_admin() or (
        current_user.is_driver() and phoi.driver_id == current_user.id and phoi.status != 'confirmed'
    )
    if not can_edit:
        flash('Bạn không có quyền sửa phơi này.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    trucks = Truck.query.filter_by(is_active=True).all()
    customers = Customer.query.filter_by(is_active=True).order_by(Customer.name).all()

    if request.method == 'POST':
        try:
            phoi.truck_id = int(request.form.get('truck_id', phoi.truck_id))
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

            db.session.commit()
            flash(f'Đã cập nhật phơi {phoi.phoi_number}.', 'success')
            return redirect(url_for('phoi.detail', id=id))

        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')

    return render_template('phoi/edit.html', phoi=phoi, trucks=trucks, customers=customers)


@bp.route('/phoi/<int:id>/confirm', methods=['POST'])
@login_required
def confirm(id):
    if not current_user.is_manager_or_admin():
        flash('Bạn không có quyền xác nhận phơi.', 'danger')
        return redirect(url_for('phoi.index'))

    phoi = Phoi.query.get_or_404(id)

    if phoi.status == 'confirmed':
        flash('Phơi này đã được xác nhận từ trước.', 'warning')
        return redirect(url_for('phoi.detail', id=id))

    # Kiểm tra: phải có ít nhất 1 lần đổ xăng gắn vào
    if phoi.fuel_logs.count() == 0:
        flash(f'Phơi {phoi.phoi_number} chưa được gắn với lần đổ xăng nào. '
              'Vui lòng ghi nhận đổ xăng và gắn vào phơi trước khi xác nhận.', 'danger')
        return redirect(url_for('phoi.detail', id=id))

    phoi.status = 'confirmed'
    phoi.confirmed_by_id = current_user.id
    phoi.confirmed_at = datetime.utcnow()
    db.session.commit()

    flash(f'Đã xác nhận phơi {phoi.phoi_number}. Balance: {phoi.balance():,.0f} VNĐ', 'success')
    return redirect(url_for('phoi.detail', id=id))
