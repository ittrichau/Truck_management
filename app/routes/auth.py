from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db, limiter
from app.models import User

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=['POST'], error_message="Quá nhiều lần đăng nhập. Vui lòng thử lại sau 1 phút.")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('phoi.index'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            if user.is_active:
                login_user(user)
                flash(f'Chào mừng {user.full_name}!', 'success')
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                if user.is_driver():
                    return redirect(url_for('phoi.create'))
                else:
                    return redirect(url_for('phoi.index'))
            else:
                flash('Tài khoản đã bị khóa.', 'danger')
        else:
            flash('Sai tên đăng nhập hoặc mật khẩu.', 'danger')

    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Đã đăng xuất.', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not current_user.check_password(current_password):
            flash('Mật khẩu hiện tại không đúng.', 'danger')
        elif new_password != confirm_password:
            flash('Mật khẩu mới không khớp.', 'danger')
        elif len(new_password) < 6:
            flash('Mật khẩu phải có ít nhất 6 ký tự.', 'danger')
        else:
            current_user.set_password(new_password)
            db.session.commit()
            flash('Đổi mật khẩu thành công!', 'success')
            return redirect(url_for('auth.profile'))

    return render_template('profile.html')
