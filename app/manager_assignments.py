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


def assign_resources(form, actor):
    """Validate the edited rows first, then apply the whole batch atomically.

    Unedited rows do not overwrite concurrent changes. Linked drivers follow
    their truck even when the submitted driver row still has its original owner.
    The caller commits all resource changes and their audits in one transaction.
    """
    from werkzeug.datastructures import MultiDict

    if not actor.is_admin():
        raise ValueError('Chỉ admin được phân quyền quản lý.')
    models = {'truck': Truck, 'driver': User, 'customer': Customer}
    tokens = form.getlist('rows')
    if len(tokens) != len(set(tokens)):
        raise ValueError('Có mục phân quyền bị gửi trùng. Vui lòng tải lại trang.')
    changes = []
    for token in sorted(tokens):
        parts = token.split(':')
        if len(parts) != 2 or parts[0] not in models or not parts[1].isdecimal():
            raise ValueError('Dữ liệu phân quyền không hợp lệ.')
        kind, raw_id = parts
        identity = int(raw_id)
        if identity <= 0 or str(identity) != raw_id:
            raise ValueError('Dữ liệu phân quyền không hợp lệ.')
        key = f'{kind}_{identity}'
        expected = form.get(f'expected_{key}')
        if expected is None:
            raise ValueError('Biểu mẫu thiếu dữ liệu đối chiếu. Vui lòng tải lại trang.')
        if kind == 'customer':
            values = form.getlist(f'managers_{key}')
            if any(not value.isdecimal() for value in values):
                raise ValueError('Quản lý không hợp lệ.')
            desired = ','.join(map(str, sorted(set(map(int, values)))))
        else:
            # Disabled controls for linked drivers are intentionally not sent.
            desired = form.get(f'manager_{key}', expected)
            if desired and not desired.isdecimal():
                raise ValueError('Quản lý không hợp lệ.')
        if desired == expected:
            continue
        resource = models[kind].query.filter_by(id=identity).with_for_update().first()
        if resource is None or (kind == 'driver' and resource.role != 'driver'):
            raise ValueError('Mục đã chỉnh không còn tồn tại. Vui lòng tải lại trang.')
        current = (','.join(map(str, sorted(user.id for user in resource.managers)))
                   if kind == 'customer' else owner_token(resource.manager_id))
        if expected != current:
            raise ValueError('Quyền của một mục vừa thay đổi. Chưa lưu mục nào; vui lòng tải lại trang và kiểm tra.')
        managers = [int(value) for value in desired.split(',') if value]
        valid = User.query.filter(User.id.in_(managers), User.role == 'manager', User.is_active.is_(True)).count()
        if valid != len(managers):
            raise ValueError('Quản lý không tồn tại hoặc đã ngừng hoạt động. Chưa lưu mục nào.')
        changes.append((kind, identity, desired, resource))

    # Apply truck transfers first so any explicitly edited linked driver is
    # validated against the final truck owner, independent of form row order.
    order = {'truck': 0, 'driver': 1, 'customer': 2}
    for kind, identity, desired, resource in sorted(changes, key=lambda item: (order[item[0]], item[1])):
        expected = (','.join(map(str, sorted(user.id for user in resource.managers)))
                    if kind == 'customer' else owner_token(resource.manager_id))
        if expected == desired:
            continue  # The truck transfer already updated this linked driver.
        row = MultiDict([('expected', expected)])
        if kind == 'customer':
            row.setlist('manager_ids', desired.split(',') if desired else [])
        else:
            row['manager_id'] = desired
        assign_resource(kind, identity, row, actor)
    return len(changes)
