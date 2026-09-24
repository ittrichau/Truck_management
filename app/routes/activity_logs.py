from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models import ActivityLog, User
from datetime import datetime

bp = Blueprint('activity_logs', __name__)


@bp.route('/activity-logs')
@login_required
def index():
    """Admin-only page to view all activity logs."""
    if not current_user.is_admin():
        flash('Bạn không có quyền truy cập.', 'danger')
        return redirect(url_for('phoi.index'))

    page = request.args.get('page', 1, type=int)
    per_page = 50

    # Filters
    action_filter = request.args.get('action', '')
    user_filter = request.args.get('user', '', type=int)
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')

    # Build query
    query = ActivityLog.query

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)

    if user_filter:
        query = query.filter(ActivityLog.user_id == user_filter)

    if date_from:
        try:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(ActivityLog.created_at >= dt_from)
        except ValueError:
            pass

    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(ActivityLog.created_at <= dt_to)
        except ValueError:
            pass

    query = query.order_by(ActivityLog.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    # For user filter dropdown
    users = User.query.order_by(User.full_name).all()

    # Available actions for filter dropdown
    actions = ['CREATE', 'UPDATE', 'DELETE', 'LOGIN', 'LOGOUT']

    return render_template(
        'activity_logs/index.html',
        logs=logs,
        pagination=pagination,
        users=users,
        actions=actions,
        action_filter=action_filter,
        user_filter=user_filter,
        date_from=date_from,
        date_to=date_to
    )