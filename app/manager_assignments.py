"""Admin assignment operations. Caller commits ownership and audit together."""
import json

from app import db
from app.models import ActivityLog, Customer, Truck, User


def owner_token(value):
    return str(value) if value is not None else ''


def assign_resource(kind, identity, form, actor):
    if not actor.is_admin():
        raise ValueError('Chỉ admin được phân quyền quản lý.')
    model = {'truck': Truck, 'driver': User, 'customer': Customer}.get(kind)
    if model is None:
        raise ValueError('Loại dữ liệu không hợp lệ.')
    resource = model.query.filter_by(id=identity).with_for_update().first()
    if resource is None or (kind == 'driver' and resource.role != 'driver'):
        raise ValueError('Dữ liệu không tồn tại.')
    if kind == 'customer':
        # Lock the customer row before reading the many-to-many assignment.
        before = sorted(user.id for user in resource.managers)
        expected = ','.join(map(str, before))
        if form.get('expected', None) != expected:
            raise ValueError('Quyền vừa thay đổi. Vui lòng tải lại trang trước khi lưu.')
        raw_ids = form.getlist('manager_ids')
        if any(not value.isdecimal() for value in raw_ids):
            raise ValueError('Quản lý không hợp lệ.')
        ids = set(map(int, raw_ids))
        managers = User.query.filter(User.id.in_(ids), User.role == 'manager', User.is_active.is_(True)).all()
        if len(managers) != len(ids):
            raise ValueError('Quản lý không tồn tại hoặc đã ngừng hoạt động.')
        resource.managers = managers
        after = sorted(ids)
    else:
        before = resource.manager_id
        if form.get('expected', None) != owner_token(before):
            raise ValueError('Quyền vừa thay đổi. Vui lòng tải lại trang trước khi lưu.')
        raw_owner = form.get('manager_id', '')
        if raw_owner:
            manager = User.query.filter_by(id=int(raw_owner), role='manager', is_active=True).first()
            if manager is None:
                raise ValueError('Quản lý không tồn tại hoặc đã ngừng hoạt động.')
            after = manager.id
        else:
            after = None
        if kind == 'driver' and resource.current_truck_id:
            truck = db.session.get(Truck, resource.current_truck_id)
            if truck.manager_id != after:
                raise ValueError('Tài xế đang giữ xe của quản lý khác. Hãy chuyển quyền xe trước; tài xế sẽ chuyển cùng xe.')
        resource.manager_id = after
        if kind == 'truck':
            # Preserve the one-driver/one-truck link when moving a vehicle.
            driver = User.query.filter_by(current_truck_id=resource.id, role='driver').with_for_update().first()
            if driver:
                driver.manager_id = after
    db.session.add(ActivityLog(
        user_id=actor.id, username=actor.username, action='UPDATE',
        resource_type='manager_assignments', resource_id=str(identity),
        details=json.dumps({'kind': kind, 'before': before, 'after': after}, ensure_ascii=False),
        method='POST', endpoint='management.index', status_code=302,
    ))
