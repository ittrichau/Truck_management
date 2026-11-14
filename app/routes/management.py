from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.manager_assignments import assign_resource
from app.models import Customer, Truck, User

bp = Blueprint('management', __name__)


@bp.route('/admin/management', methods=['GET', 'POST'])
@login_required
def index():
    if not current_user.is_admin():
        abort(403)
    if request.method == 'POST':
        try:
            assign_resource(request.form.get('kind'), int(request.form.get('resource_id', '')),
                            request.form, current_user)
            db.session.commit()
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc) or 'Dữ liệu không hợp lệ.', 'danger')
            return render_page(), 400
        except SQLAlchemyError:
            db.session.rollback()
            flash('Không thể lưu phân quyền. Dữ liệu chưa thay đổi, vui lòng thử lại.', 'danger')
            return render_page(), 409
        flash('Đã cập nhật phân quyền. Khi chuyển xe, tài xế đang giữ xe và lịch sử xe đi theo quản lý mới.', 'success')
        return redirect(url_for('management.index'))
    return render_page()


def render_page():
    return render_template('management/index.html',
        managers=User.query.filter_by(role='manager', is_active=True).order_by(User.full_name).all(),
        trucks=Truck.query.order_by(Truck.license_plate).all(),
        drivers=User.query.filter_by(role='driver').order_by(User.full_name).all(),
        customers=Customer.query.order_by(Customer.name).all())
