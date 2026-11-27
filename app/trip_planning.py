"""Manager-owned schedules. Planning never writes back to a phơi."""
from datetime import date, datetime
import hashlib
import json
import re

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import db
from app.models import Customer, Phoi, Truck, User


MATCH_WINDOW_DAYS = 7
FIELD_LABELS = {
    'truck_id': 'Xe', 'driver_id': 'Tài xế', 'customer_id': 'Khách hàng',
    'departure_date': 'Ngày đi', 'return_date': 'Ngày về',
    'origin': 'Điểm đi', 'destination': 'Điểm đến',
    'cargo_description': 'Hàng chuyến đi', 'return_trips': 'Các chặng về',
}


class TripPlan(db.Model):
    __tablename__ = 'trip_plans'

    id = db.Column(db.Integer, primary_key=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    truck_id = db.Column(db.Integer, db.ForeignKey('trucks.id'), nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    departure_date = db.Column(db.Date, nullable=False, index=True)
    return_date = db.Column(db.Date)
    origin = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    cargo_description = db.Column(db.String(300))
    return_load_status = db.Column(db.String(20), nullable=False, default='unknown')
    return_trips = db.Column(db.JSON, nullable=False, default=list)
    notes = db.Column(db.Text)
    is_cancelled = db.Column(db.Boolean, nullable=False, default=False)
    phoi_id = db.Column(db.Integer, db.ForeignKey('phoi.id'), unique=True)
    original_data = db.Column(db.JSON, nullable=False, default=dict)
    actual_data = db.Column(db.JSON)
    reviewed_signature = db.Column(db.String(64))
    synced_at = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    version = db.Column(db.Integer, nullable=False, default=1)
    __mapper_args__ = {'version_id_col': version}
    __table_args__ = (
        db.CheckConstraint('return_date IS NULL OR return_date >= departure_date', name='ck_trip_plan_dates'),
        db.CheckConstraint("return_load_status IN ('unknown', 'loaded', 'empty')", name='ck_trip_plan_return_load'),
    )

    truck = db.relationship('Truck', foreign_keys=[truck_id])
    driver = db.relationship('User', foreign_keys=[driver_id])
    customer = db.relationship('Customer', foreign_keys=[customer_id])
    phoi = db.relationship('Phoi', foreign_keys=[phoi_id])
    history = db.relationship('TripPlanHistory', order_by='TripPlanHistory.id.desc()', lazy='select')

    def planned_data(self, session):
        truck = session.get(Truck, self.truck_id)
        driver = session.get(User, self.driver_id) if self.driver_id else None
        customer = session.get(Customer, self.customer_id) if self.customer_id else None
        return {
            'truck_id': self.truck_id, 'truck_name': truck.license_plate if truck else '',
            'driver_id': self.driver_id, 'driver_name': driver.full_name if driver else '',
            'customer_id': self.customer_id, 'customer_name': customer.name if customer else '',
            'departure_date': iso(self.departure_date), 'return_date': iso(self.return_date),
            'origin': self.origin, 'destination': self.destination,
            'cargo_description': self.cargo_description or '',
            'return_load_status': self.return_load_status, 'return_trips': self.return_trips or [],
        }

    def audit_data(self, session):
        return dict(self.planned_data(session), phoi_id=self.phoi_id,
                    actual_data=self.actual_data, is_cancelled=self.is_cancelled,
                    reviewed_signature=self.reviewed_signature, notes=self.notes or '')

    def signature(self, session, actual=None):
        payload = [self.planned_data(session), actual if actual is not None else self.actual_data]
        return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def differences(self, session, actual=None):
        actual = self.actual_data if actual is None else actual
        if not actual:
            return []
        planned = self.planned_data(session)
        differences = []
        for field, label in FIELD_LABELS.items():
            # An unassigned driver is not a discrepancy.
            if field == 'driver_id' and not planned[field]:
                continue
            if canonical(field, planned.get(field)) != canonical(field, actual.get(field)):
                differences.append({'field': field, 'label': label,
                                    'planned': display_value(field, planned),
                                    'actual': display_value(field, actual)})
        if self.return_load_status == 'empty' and actual.get('return_trips'):
            differences.append({'field': 'return_load_status', 'label': 'Hàng về',
                                'planned': 'Về rỗng', 'actual': 'Có hàng về'})
        if actual.get('cancelled'):
            differences.append({'field': 'cancelled', 'label': 'Phơi',
                                'planned': 'Chuyến theo kế hoạch', 'actual': 'Phơi đã hủy'})
        return differences

    def status(self, session, actual=None, draft=False):
        if self.is_cancelled:
            return 'cancelled', 'Đã hủy kế hoạch'
        if not (actual or self.actual_data):
            return 'planned', 'Đã lập kế hoạch'
        differences = self.differences(session, actual)
        if draft:
            return ('review', 'Có khác biệt · Phơi chưa chốt') if differences else ('running', 'Phơi chưa chốt')
        if differences:
            if self.reviewed_signature == self.signature(session, actual):
                return 'reviewed', 'Đã kiểm tra · Giữ kế hoạch'
            return 'review', 'Có khác biệt · Cần kiểm tra'
        return 'matched', 'Khớp thực tế'

    def record(self, session, action, before, reason='', actor_id=None):
        session.add(TripPlanHistory(plan_id=self.id, actor_id=actor_id, action=action,
                                    reason=reason, before_data=before, after_data=self.audit_data(session)))

    def sync_actual(self, session, phoi, actor_id=None):
        actual = actual_from_phoi(phoi)
        if self.actual_data == actual:
            return False
        before = self.audit_data(session)
        self.actual_data = actual
        self.synced_at = datetime.utcnow()
        self.reviewed_signature = None
        self.record(session, 'sync', before, 'Cập nhật thực tế từ phơi', actor_id)
        return True

    def link_phoi(self, session, phoi, actor_id, reason):
        if self.is_cancelled:
            raise ValueError('Kế hoạch đã hủy không thể liên kết phơi.')
        if phoi.status == 'cancelled' or phoi.truck.manager_id != self.manager_id:
            raise ValueError('Phơi không hợp lệ hoặc không thuộc cùng quản lý với kế hoạch.')
        occupied = session.scalar(select(TripPlan).where(TripPlan.phoi_id == phoi.id, TripPlan.id != self.id))
        if occupied:
            raise ValueError('Phơi đã được liên kết với kế hoạch khác.')
        before = self.audit_data(session)
        self.phoi_id = phoi.id
        self.actual_data = actual_from_phoi(phoi)
        self.synced_at = datetime.utcnow()
        self.reviewed_signature = None
        self.record(session, 'link', before, reason, actor_id)

    def review(self, session, actor_id, reason, expected_signature, accept=False):
        if self.is_cancelled or not self.phoi or self.phoi.status not in ('submitted', 'confirmed'):
            raise ValueError('Chỉ đối soát kế hoạch đang hoạt động có phơi đã chốt.')
        if self.phoi.truck.manager_id != self.manager_id or self.truck.manager_id != self.manager_id:
            raise ValueError('Phạm vi quản lý của xe/phơi đã thay đổi. Hãy kiểm tra lại liên kết.')
        # Pull the latest committed phơi before accepting or acknowledging differences.
        self.sync_actual(session, self.phoi, actor_id)
        if expected_signature != self.signature(session):
            raise ValueError('Thông tin phơi vừa thay đổi. Vui lòng tải lại và kiểm tra trước khi đối soát.')
        before = self.audit_data(session)
        if self.actual_data.get('cancelled'):
            raise ValueError('Phơi đã hủy; hãy liên kết lại hoặc hủy kế hoạch.')
        if accept:
            actual = self.actual_data
            for field in ('truck_id', 'driver_id', 'customer_id', 'origin', 'destination', 'cargo_description',
                          'return_load_status', 'return_trips'):
                setattr(self, field, actual[field])
            self.departure_date = date.fromisoformat(actual['departure_date'])
            self.return_date = date.fromisoformat(actual['return_date']) if actual['return_date'] else None
            if self.return_date and self.return_date < self.departure_date:
                raise ValueError('Ngày về trên phơi trước ngày đi. Hãy kiểm tra lại phơi.')
        self.reviewed_signature = self.signature(session)
        self.record(session, 'accept' if accept else 'review', before, reason, actor_id)


class TripPlanHistory(db.Model):
    __tablename__ = 'trip_plan_history'
    id = db.Column(db.Integer, primary_key=True)
    plan_id = db.Column(db.Integer, db.ForeignKey('trip_plans.id'), nullable=False, index=True)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    action = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(500), nullable=False, default='')
    before_data = db.Column(db.JSON)
    after_data = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    actor = db.relationship('User', foreign_keys=[actor_id])


def iso(value):
    return value.isoformat() if value else None


def canonical(field, value):
    if field == 'return_trips':
        return [{key: canonical(key, row.get(key)) for key in (
            'customer_id', 'return_date', 'origin', 'destination', 'cargo_description'
        )} for row in value or []]
    if isinstance(value, str):
        return ' '.join(value.split()).casefold()
    return value or None


def display_value(field, data):
    if field.endswith('_id'):
        return data.get(field.replace('_id', '_name')) or 'Chưa phân công'
    if field in ('departure_date', 'return_date'):
        return date.fromisoformat(data[field]).strftime('%d/%m/%Y') if data.get(field) else 'Chưa ghi nhận'
    if field == 'return_trips':
        return '; '.join(
            f"{index + 1}. {row.get('customer_name') or 'Chưa có khách'}: "
            f"{row.get('origin') or '?'} → {row.get('destination') or '?'}"
            f" · {display_value('return_date', row)} · {row.get('cargo_description') or 'Chưa ghi hàng'}"
            for index, row in enumerate(data.get(field) or [])
        ) or ('Về rỗng (dự kiến)' if data.get('return_load_status') == 'empty' else 'Chưa khai báo hàng về')
    return data.get(field) or 'Chưa ghi nhận'


def actual_from_phoi(phoi):
    return {
        'truck_id': phoi.truck_id, 'truck_name': phoi.truck.license_plate,
        'driver_id': phoi.driver_id, 'driver_name': phoi.driver.full_name,
        'customer_id': phoi.customer_id, 'customer_name': phoi.customer.name if phoi.customer else '',
        'departure_date': iso(phoi.departure_date), 'return_date': iso(phoi.return_date),
        'origin': phoi.origin, 'destination': phoi.destination,
        'cargo_description': phoi.cargo_summary(),
        'return_load_status': 'loaded' if phoi.return_trips.count() else 'unknown',
        'return_trips': [{
            'customer_id': trip.customer_id, 'customer_name': trip.customer.name if trip.customer else '',
            'return_date': iso(trip.return_date), 'origin': trip.origin,
            'destination': trip.destination, 'cargo_description': trip.cargo_summary(),
        } for trip in phoi.return_trips.all()],
        'cancelled': phoi.status == 'cancelled',
    }


def match_bounds(day):
    return (date.fromordinal(max(date.min.toordinal(), day.toordinal() - MATCH_WINDOW_DAYS)),
            date.fromordinal(min(date.max.toordinal(), day.toordinal() + MATCH_WINDOW_DAYS)))


def candidate_phois(session, plan):
    """Suggestions only: always require a unique match in both directions."""
    low, high = match_bounds(plan.departure_date)
    used = select(TripPlan.phoi_id).where(TripPlan.phoi_id.isnot(None))
    return session.scalars(select(Phoi).join(Truck).where(
        Phoi.truck_id == plan.truck_id, Truck.manager_id == plan.manager_id,
        Phoi.customer_id == plan.customer_id, Phoi.status != 'cancelled',
        Phoi.departure_date.between(low, high), ~Phoi.id.in_(used),
    ).order_by(Phoi.departure_date, Phoi.id)).all()


def candidate_plans(session, phoi):
    low, high = match_bounds(phoi.departure_date)
    return session.scalars(select(TripPlan).join(Truck, TripPlan.truck_id == Truck.id).where(
        TripPlan.phoi_id.is_(None), TripPlan.is_cancelled.is_(False),
        TripPlan.truck_id == phoi.truck_id, TripPlan.customer_id == phoi.customer_id,
        TripPlan.manager_id == phoi.truck.manager_id, Truck.manager_id == TripPlan.manager_id,
        TripPlan.departure_date.between(low, high),
    )).all()


def unique_candidate(session, plan):
    if not plan.customer_id:
        return None
    candidates = candidate_phois(session, plan)
    if len(candidates) == 1 and len(candidate_plans(session, candidates[0])) == 1:
        return candidates[0]
    return None


def sync_phoi(session, phoi_id, actor_id=None):
    phoi = session.get(Phoi, phoi_id)
    if not phoi:
        return
    plan = session.scalar(select(TripPlan).where(TripPlan.phoi_id == phoi.id).with_for_update())
    if not plan and phoi.status in ('submitted', 'confirmed'):
        candidates = candidate_plans(session, phoi)
        if len(candidates) == 1 and unique_candidate(session, candidates[0]) == phoi:
            plan = candidates[0]
            before = plan.audit_data(session)
            plan.phoi_id = phoi.id
            plan.record(session, 'link', before, 'Tự ghép theo xe, khách và ngày trong phạm vi 7 ngày', actor_id)
    # Ownership transfers never publish a new manager's phơi into an old plan.
    if plan and phoi.truck.manager_id == plan.manager_id and plan.truck.manager_id == plan.manager_id:
        plan.sync_actual(session, phoi, actor_id)


def sync_after_phoi_commit(phoi_id, actor_id=None):
    """A planning failure must never undo or block the driver's committed work."""
    try:
        with Session(db.engine) as session:
            sync_phoi(session, phoi_id, actor_id)
            session.commit()
    except Exception:
        current_app.logger.exception('Không thể đồng bộ kế hoạch cho phơi %s; có thể đồng bộ lại trên trang kế hoạch.', phoi_id)


def parse_day(value, label, required=False):
    if not value and not required:
        return None
    if not value or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
        raise ValueError(f'{label} không hợp lệ.')
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{label} không hợp lệ.') from None


def parse_id(value, label, required=False):
    if not value and not required:
        return None
    if not value or not re.fullmatch(r'[0-9]{1,10}', value) or not 0 < int(value) <= 2147483647:
        raise ValueError(f'{label} không hợp lệ.')
    return int(value)


def form_values(form, actor, existing=None):
    """Validate the entire schedule before mutating it or its history."""
    from app.access import customers_query, drivers_query, trucks_query

    def text(key, label, limit, required=False):
        value = form.get(key, '').strip()
        if (required and not value) or len(value) > limit:
            raise ValueError(f'{label} bắt buộc và tối đa {limit} ký tự.' if required
                             else f'{label} tối đa {limit} ký tự.')
        return value

    truck_id = parse_id(form.get('truck_id'), 'Xe', True)
    truck = trucks_query(actor).filter_by(id=truck_id).first()
    if not truck or (not truck.is_active and (not existing or existing.truck_id != truck.id)):
        raise ValueError('Xe không hoạt động hoặc không thuộc phạm vi quản lý.')
    owner = db.session.get(User, truck.manager_id) if truck.manager_id else None
    if not owner or owner.role != 'manager' or not owner.is_active:
        raise ValueError('Xe cần được giao cho một quản lý đang hoạt động trước khi lập kế hoạch.')
    if existing and truck.manager_id != existing.manager_id:
        raise ValueError('Xe mới phải thuộc cùng quản lý với kế hoạch.')
    driver_id = parse_id(form.get('driver_id'), 'Tài xế')
    if driver_id:
        driver = drivers_query(actor).filter_by(id=driver_id, manager_id=truck.manager_id).first()
        if not driver or (not driver.is_active and (not existing or existing.driver_id != driver.id)):
            raise ValueError('Tài xế không hoạt động hoặc không thuộc cùng quản lý với xe.')

    historical = set()
    if existing:
        historical = {existing.customer_id} | {row.get('customer_id') for row in existing.return_trips or []}

    def customer(value, allowed_history):
        identity = parse_id(value, 'Khách hàng')
        if not identity:
            return None
        query = customers_query(actor).filter_by(id=identity, is_active=True)
        found = db.session.get(Customer, identity) if identity in allowed_history else query.first()
        if not found:
            raise ValueError('Khách hàng không hoạt động hoặc không thuộc phạm vi được giao.')
        if actor.is_admin() and identity not in allowed_history and owner not in found.managers:
            raise ValueError('Khách hàng chưa được giao cho quản lý của xe.')
        return found

    selected_customer = customer(form.get('customer_id'), {existing.customer_id} if existing else set())
    departure = parse_day(form.get('departure_date'), 'Ngày đi', True)
    returned = parse_day(form.get('return_date'), 'Ngày về')
    if returned and returned < departure:
        raise ValueError('Ngày về không được trước ngày đi.')
    load_status = form.get('return_load_status', 'unknown')
    if load_status not in ('unknown', 'loaded', 'empty'):
        raise ValueError('Tình trạng hàng về không hợp lệ.')
    fields = ('customer_id', 'return_date', 'origin', 'destination', 'cargo_description')
    lists = {field: form.getlist('return_' + field + '[]') for field in fields}
    lengths = {len(values) for values in lists.values()}
    if len(lengths) != 1 or max(lengths, default=0) > 20:
        raise ValueError('Danh sách chặng về không hợp lệ, tối đa 20 chặng.')
    returns = []
    previous_day = departure
    for index in range(len(lists['origin'])):
        row = {field: lists[field][index].strip() for field in fields}
        if not any(row.values()):
            continue
        if load_status != 'loaded':
            raise ValueError('Chọn “Đã có hàng về” khi nhập các chặng về.')
        if not row['origin'] or not row['destination'] or len(row['origin']) > 200 or len(row['destination']) > 200:
            raise ValueError('Mỗi chặng về cần điểm đi và điểm đến, tối đa 200 ký tự.')
        if len(row['cargo_description']) > 300:
            raise ValueError('Hàng chặng về tối đa 300 ký tự.')
        day = parse_day(row['return_date'], 'Ngày chạy chặng về')
        if day and (day < previous_day or (returned and day > returned)):
            raise ValueError('Ngày các chặng về phải theo thứ tự, từ ngày đi đến ngày về bãi.')
        previous_day = day or previous_day
        selected = customer(row['customer_id'], historical)
        row.update(customer_id=selected.id if selected else None,
                   customer_name=selected.name if selected else '', return_date=iso(day))
        returns.append(row)
    if load_status == 'loaded' and not returns:
        raise ValueError('Vui lòng nhập ít nhất một chặng khi đã có hàng về.')
    return dict(manager_id=truck.manager_id, truck_id=truck.id, driver_id=driver_id,
                customer_id=selected_customer.id if selected_customer else None,
                departure_date=departure, return_date=returned,
                origin=text('origin', 'Điểm đi', 200, True),
                destination=text('destination', 'Điểm đến', 200, True),
                cargo_description=text('cargo_description', 'Hàng chuyến đi', 300),
                return_load_status=load_status, return_trips=returns, notes=text('notes', 'Ghi chú', 2000))
