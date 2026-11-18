"""Read-only financial reports for managers and admins."""
import calendar
import re
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, abort, render_template, request
from flask_login import current_user, login_required

from app.access import trucks_query
from app.models import Truck
from app.truck_reports import build_truck_report


bp = Blueprint('reports', __name__)


@bp.route('/reports')
@login_required
def index():
    if not current_user.is_manager_or_admin():
        abort(403)

    today = datetime.now(timezone(timedelta(hours=7))).date()
    mode = request.args.get('mode', 'month')
    month = request.args.get('month', today.strftime('%Y-%m')).strip()
    start_date = request.args.get('start_date', today.replace(day=1).isoformat()).strip()
    end_date = request.args.get('end_date', today.isoformat()).strip()
    raw_truck = request.args.get('truck_id', '').strip()
    trucks = trucks_query().order_by(Truck.license_plate).all()
    truck_id = None
    if raw_truck:
        if not raw_truck.isascii() or not raw_truck.isdigit() or len(raw_truck) > 10:
            abort(400, description='Xe không hợp lệ.')
        truck_id = int(raw_truck)
        if truck_id not in {truck.id for truck in trucks}:
            abort(404)

    error = None
    report = None
    try:
        if mode == 'month':
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}', month):
                raise ValueError('Vui lòng chọn tháng hợp lệ.')
            try:
                start_day = date.fromisoformat(month + '-01')
            except ValueError:
                raise ValueError('Vui lòng chọn tháng hợp lệ.') from None
            end_day = start_day.replace(day=calendar.monthrange(start_day.year, start_day.month)[1])
        elif mode == 'range':
            if not all(re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value)
                       for value in (start_date, end_date)):
                raise ValueError('Vui lòng nhập đủ ngày bắt đầu và kết thúc hợp lệ.')
            try:
                start_day, end_day = date.fromisoformat(start_date), date.fromisoformat(end_date)
            except ValueError:
                raise ValueError('Vui lòng nhập ngày hợp lệ.') from None
            if start_day > end_day:
                raise ValueError('Ngày bắt đầu không được sau ngày kết thúc.')
            if (end_day.year - start_day.year) * 12 + end_day.month - start_day.month >= 120:
                raise ValueError('Vui lòng chọn khoảng thời gian không quá 120 tháng.')
        else:
            raise ValueError('Chế độ xem không hợp lệ. Hãy chọn theo tháng hoặc khoảng thời gian.')
    except ValueError as exc:
        error = str(exc)

    if error is None:
        report = build_truck_report(current_user, trucks, start_day, end_day, truck_id)

    return render_template(
        'reports/index.html', report=report, error=error, trucks=trucks,
        filter_truck_id=truck_id, mode=mode, month=month,
        start_date=start_date, end_date=end_date,
        period_label=(f'{start_day:%d/%m/%Y} – {end_day:%d/%m/%Y}' if report else ''),
    ), 400 if error else 200
