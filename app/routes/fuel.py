from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app
from flask_login import login_required, current_user
from app import db
from app.models import FuelLog, FuelPrice, Truck, Phoi
from datetime import datetime, date

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
    # Chỉ hiển thị phơi đang tiến hành (chưa confirmed)
    phois = Phoi.query.filter(
        Phoi.status.in_(['draft', 'submitted'])
    ).order_by(Phoi.created_at.desc()).all()

    if request.method == 'POST':
        try:
            liters = float(request.form.get('liters', 0))
            refuel_date_str = request.form.get('refuel_date', '')
            refuel_date = datetime.strptime(refuel_date_str, '%Y-%m-%d').date() if refuel_date_str else date.today()

            # Tự động lấy giá xăng từ bảng FuelPrice
            fuel_price = _get_active_price_or_none(refuel_date)
            if fuel_price:
                price = fuel_price.price_per_liter
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
                km_at_refuel=int(request.form.get('km_at_refuel', 0) or 0),
                refuel_date=refuel_date,
                is_substitute=is_substitute,
                notes=request.form.get('notes', '').strip(),
                created_by_id=current_user.id
            )

            # Gắn nhiều phơi — bắt buộc ít nhất 1 phơi, phải cùng xe
            selected_phoi_ids = request.form.getlist('phoi_ids')
            attached_count = 0
            for pid in selected_phoi_ids:
                if pid:
                    phoi = Phoi.query.get(int(pid))
                    if not phoi:
                        continue
                    if phoi.truck_id != truck_id:
                        flash(f'Phơi {phoi.phoi_number} không thuộc xe đã chọn. Vui lòng chọn phơi của cùng xe.', 'danger')
                        return render_template('fuel/create.html', trucks=trucks, phois=phois,
                                               current_price=_get_active_price_or_none())
                    log.phois.append(phoi)
                    attached_count += 1

            if attached_count == 0:
                flash('Phải gắn ít nhất một phơi đang tiến hành cho lần đổ xăng này.', 'danger')
                return render_template('fuel/create.html', trucks=trucks, phois=phois,
                                       current_price=_get_active_price_or_none())

            truck = Truck.query.get(log.truck_id)
            if truck and log.km_at_refuel > truck.current_km:
                truck.current_km = log.km_at_refuel

            db.session.add(log)
            db.session.commit()
            flash(f'Đã ghi nhận đổ {liters} lít xăng (giá {price:,.0f}đ/lít).', 'success')
            return redirect(url_for('fuel.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Lỗi: {str(e)}', 'danger')

    # GET: hiển thị giá xăng mặc định nếu có
    return render_template('fuel/create.html', trucks=trucks, phois=phois,
                           current_price=_get_active_price_or_none())


@bp.route('/fuel/<int:id>/delete', methods=['POST'])
@login_required
def delete(id):
    if not current_user.is_manager_or_admin():
        flash('Không có quyền xóa.', 'danger')
        return redirect(url_for('fuel.index'))
    log = FuelLog.query.get_or_404(id)
    db.session.delete(log)
    db.session.commit()
    flash('Đã xóa bản ghi đổ xăng.', 'success')
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


@bp.route('/fuel/prices/create', methods=['GET', 'POST'])
@login_required
def create_price():
    if not current_user.is_admin():
        flash('Chỉ admin mới được tạo giá xăng.', 'danger')
        return redirect(url_for('fuel.price_list'))
    if request.method == 'POST':
        try:
            from datetime import timedelta

            # Parse datetime từ form (định dạng: YYYY-MM-DDTHH:MM)
            effective_from_str = request.form.get('effective_from', '')
            # Mặc định 3:00 PM (15:00) nếu không nhập giờ
            now = datetime.now()
            default_from = now.replace(hour=15, minute=0, second=0, microsecond=0)
            effective_from = datetime.strptime(effective_from_str, '%Y-%m-%dT%H:%M') if effective_from_str else default_from

            effective_to_str = request.form.get('effective_to', '').strip()
            effective_to = datetime.strptime(effective_to_str, '%Y-%m-%dT%H:%M') if effective_to_str else None

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