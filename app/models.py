from app import db, login_manager
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date

def generate_phoi_number():
    """Generate phoi number: P-YYYYMMDD-NNN"""
    today = date.today().strftime('%Y%m%d')
    last = Phoi.query.filter(Phoi.phoi_number.like(f'P-{today}-%')).order_by(Phoi.id.desc()).first()
    if last:
        num = int(last.phoi_number.split('-')[-1]) + 1
    else:
        num = 1
    return f'P-{today}-{num:03d}'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(15))
    role = db.Column(db.String(20), nullable=False, default='driver')  # driver, manager, admin
    is_active = db.Column(db.Boolean, default=True)
    current_truck_id = db.Column(db.Integer, db.ForeignKey('trucks.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Ràng buộc cứng: mỗi current_truck_id chỉ xuất hiện tối đa 1 lần
    __table_args__ = (
        db.UniqueConstraint('current_truck_id', name='uq_driver_truck'),
    )
    
    # Relations
    current_truck = db.relationship('Truck', foreign_keys=[current_truck_id], post_update=True)
    created_phois = db.relationship('Phoi', foreign_keys='Phoi.driver_id', backref='driver', lazy='dynamic')
    confirmed_phois = db.relationship('Phoi', foreign_keys='Phoi.confirmed_by_id', backref='confirmer', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def is_driver(self):
        return self.role == 'driver'
    
    def is_manager_or_admin(self):
        return self.role in ['manager', 'admin']
    
    def is_admin(self):
        return self.role == 'admin'
    
    def __repr__(self):
        return f'<User {self.full_name} ({self.role})>'

class Truck(db.Model):
    __tablename__ = 'trucks'
    id = db.Column(db.Integer, primary_key=True)
    license_plate = db.Column(db.String(20), unique=True, nullable=False)
    brand = db.Column(db.String(50))
    capacity_ton = db.Column(db.Float)
    year = db.Column(db.Integer)
    fuel_rate = db.Column(db.Float, comment='Liters per 100km')
    current_km = db.Column(db.Integer, default=0)
    
    # Ngày đăng kiểm & hạn (tháng)
    inspection_date = db.Column(db.Date, nullable=True, comment='Ngày đăng kiểm gần nhất')
    inspection_expiry_months = db.Column(db.Integer, nullable=True, default=6, comment='Hạn đăng kiểm (tháng)')
    # Ngày cấp phù hiệu & hạn (tháng)
    permit_date = db.Column(db.Date, nullable=True, comment='Ngày cấp phù hiệu gần nhất')
    permit_expiry_months = db.Column(db.Integer, nullable=True, default=12, comment='Hạn phù hiệu (tháng)')
    
    # Notification tracking (cách 2 ngày nhắc lại)
    last_inspection_notified_at = db.Column(db.DateTime, nullable=True, comment='Lần cuối thông báo đăng kiểm sắp hết hạn')
    last_permit_notified_at = db.Column(db.DateTime, nullable=True, comment='Lần cuối thông báo phù hiệu sắp hết hạn')
    
    status = db.Column(db.String(20), default='available')  # available, in_trip, maintenance
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    phois = db.relationship('Phoi', backref='truck', lazy='dynamic')
    fuel_logs = db.relationship('FuelLog', backref='truck', lazy='dynamic')
    
    def trip_count(self):
        return self.phois.filter(Phoi.status == 'confirmed').count()
    
    def inspection_expiry_date(self):
        """Calculate the expiry date of inspection (date + months)."""
        if not self.inspection_date or not self.inspection_expiry_months:
            return None
        month = self.inspection_date.month + self.inspection_expiry_months
        year = self.inspection_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        day = min(self.inspection_date.day, last_day)
        return date(year, month, day)

    def inspection_days_until_expiry(self):
        """Days until inspection expires. Returns None if no data."""
        expiry = self.inspection_expiry_date()
        if not expiry:
            return None
        return (expiry - date.today()).days

    def permit_expiry_date(self):
        """Calculate the expiry date of permit (date + months)."""
        if not self.permit_date or not self.permit_expiry_months:
            return None
        month = self.permit_date.month + self.permit_expiry_months
        year = self.permit_date.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        day = min(self.permit_date.day, last_day)
        return date(year, month, day)

    def permit_days_until_expiry(self):
        """Days until permit expires. Returns None if no data."""
        expiry = self.permit_expiry_date()
        if not expiry:
            return None
        return (expiry - date.today()).days

    def inspection_should_notify(self):
        """Check if should notify about inspection expiry (within 15 days + every 2 days)."""
        days = self.inspection_days_until_expiry()
        if days is None or days > 15:
            return False
        if days < 0:
            return True
        if not self.last_inspection_notified_at:
            return True
        return (datetime.utcnow() - self.last_inspection_notified_at).days >= 2

    def permit_should_notify(self):
        """Check if should notify about permit expiry (within 15 days + every 2 days)."""
        days = self.permit_days_until_expiry()
        if days is None or days > 15:
            return False
        if days < 0:
            return True
        if not self.last_permit_notified_at:
            return True
        return (datetime.utcnow() - self.last_permit_notified_at).days >= 2

    @staticmethod
    def get_expiry_warnings():
        """Return list of (truck, type, days_left) for trucks with expiring docs."""
        from datetime import datetime as dt
        warnings = []
        trucks = Truck.query.filter_by(is_active=True).all()
        for t in trucks:
            insp_days = t.inspection_days_until_expiry()
            if insp_days is not None and insp_days <= 15 and t.inspection_should_notify():
                warnings.append((t, 'inspection', insp_days))
            perm_days = t.permit_days_until_expiry()
            if perm_days is not None and perm_days <= 15 and t.permit_should_notify():
                warnings.append((t, 'permit', perm_days))
        return warnings

    @staticmethod
    def mark_expiry_notified(notified_truck_ids, notified_types):
        """Update last_notified timestamps for sent notifications."""
        from datetime import datetime as dt
        now = dt.utcnow()
        for tid in notified_truck_ids:
            truck = Truck.query.get(tid)
            if not truck:
                continue
            if 'inspection' in notified_types.get(tid, []):
                truck.last_inspection_notified_at = now
            if 'permit' in notified_types.get(tid, []):
                truck.last_permit_notified_at = now

    def needs_refuel_warning(self):
        """Check if truck needs refuel (every 2 trips)"""
        trip_count = self.trip_count()
        if trip_count % 2 == 0 and trip_count > 0:
            last_fuel = FuelLog.query.filter_by(truck_id=self.id).order_by(FuelLog.refuel_date.desc()).first()
            if not last_fuel or (datetime.utcnow().date() - last_fuel.refuel_date).days > 7:
                return True
        return False
    
    def __repr__(self):
        return f'<Truck {self.license_plate}>'

class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    cargo_type = db.Column(db.String(100))
    default_origin = db.Column(db.String(200))
    default_destination = db.Column(db.String(200))
    contact_phone = db.Column(db.String(15))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    created_by = db.relationship('User', backref='customers')
    phois = db.relationship('Phoi', backref='customer', lazy='dynamic')
    
    def __repr__(self):
        return f'<Customer {self.name} - {self.cargo_type}>'

class Phoi(db.Model):
    __tablename__ = 'phoi'
    id = db.Column(db.Integer, primary_key=True)
    phoi_number = db.Column(db.String(20), unique=True, nullable=False)
    
    # Tài xế
    driver_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    truck_id = db.Column(db.Integer, db.ForeignKey('trucks.id'), nullable=False)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'))
    
    # Thông tin chuyến
    departure_date = db.Column(db.Date, nullable=False)
    return_date = db.Column(db.Date)
    origin = db.Column(db.String(200), nullable=False)
    destination = db.Column(db.String(200), nullable=False)
    cargo_description = db.Column(db.String(300))
    
    # Số km
    km_start = db.Column(db.Integer, default=0)
    km_end = db.Column(db.Integer, default=0)
    km_total = db.Column(db.Integer, default=0)
    
    # Tiền
    revenue_full = db.Column(db.Numeric(12, 2), default=0, comment='Tổng doanh thu full chuyến')
    revenue_collected = db.Column(db.Numeric(12, 2), default=0, comment='Tiền mặt tài xế đã thu')
    driver_wage = db.Column(db.Numeric(12, 2), default=0, comment='Phí công tài xế (manager nhập)')
    
    # Trạng thái
    status = db.Column(db.String(20), default='draft')  # draft, submitted, confirmed
    notes = db.Column(db.Text)
    
    # Người xác nhận
    confirmed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    confirmed_at = db.Column(db.DateTime)
    
    # Timestamps
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relations
    expenses = db.relationship('PhoiExpense', backref='phoi', lazy='dynamic', cascade='all, delete-orphan')
    
    def calculate_km_total(self):
        if self.km_end and self.km_start:
            self.km_total = self.km_end - self.km_start
        return self.km_total
    
    def total_expenses(self):
        """Tổng chi phí chuyến (bốc vác, phí đường, sửa xe...)"""
        return sum(exp.amount for exp in self.expenses.all())
    
    def balance(self):
        """
        Tính balance:
        - Dương: Chủ xe phải trả thêm cho tài xế
        - Âm: Tài xế phải nộp lại cho chủ xe
        """
        total_exp = self.total_expenses()
        driver_paid = total_exp  # Tài xế đã ứng chi
        driver_held = self.revenue_collected  # Tiền mặt tài xế đang giữ
        driver_wage = self.driver_wage  # Tiền công
        
        owner_owes = driver_paid + driver_wage
        driver_owes = driver_held
        
        return owner_owes - driver_owes
    
    def owner_profit(self):
        """Lợi nhuận của chủ xe"""
        return self.revenue_full - self.total_expenses() - self.driver_wage
    
    def __repr__(self):
        return f'<Phoi {self.phoi_number} [{self.status}]>'

class PhoiExpense(db.Model):
    __tablename__ = 'phoi_expenses'
    id = db.Column(db.Integer, primary_key=True)
    phoi_id = db.Column(db.Integer, db.ForeignKey('phoi.id'), nullable=False)
    category = db.Column(db.String(30), nullable=False)  # porter_fee, toll_fee, repair, other
    description = db.Column(db.String(200))
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    CATEGORIES = {
        'porter_fee': 'Bồi dưỡng bốc vác',
        'toll_fee': 'Phí đường',
        'repair': 'Sửa xe',
        'other': 'Chi phí khác'
    }
    
    def category_label(self):
        return self.CATEGORIES.get(self.category, self.category)
    
    def __repr__(self):
        return f'<PhoiExpense {self.category}: {self.amount}>'

# Bảng trung gian: nhiều-nhiều giữa FuelLog và Phoi
fuel_log_phois = db.Table('fuel_log_phois',
    db.Column('fuel_log_id', db.Integer, db.ForeignKey('fuel_logs.id'), primary_key=True),
    db.Column('phoi_id', db.Integer, db.ForeignKey('phoi.id'), primary_key=True)
)

class FuelPrice(db.Model):
    """Bảng giá xăng theo khung thời gian – admin quản lý"""
    __tablename__ = 'fuel_prices'
    id = db.Column(db.Integer, primary_key=True)
    price_per_liter = db.Column(db.Numeric(12, 2), nullable=False)
    effective_from = db.Column(db.DateTime, nullable=False, comment='Thời điểm bắt đầu hiệu lực')
    effective_to = db.Column(db.DateTime, nullable=True, comment='NULL = đang hiệu lực')
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    created_by = db.relationship('User', backref='fuel_prices')
    
    def is_effective(self, check_datetime=None):
        """Kiểm tra giá có hiệu lực tại thời điểm check_datetime không"""
        if check_datetime is None:
            check_datetime = datetime.utcnow()
        if not self.is_active or check_datetime < self.effective_from:
            return False
        if self.effective_to is not None and check_datetime > self.effective_to:
            return False
        return True
    
    @staticmethod
    def get_active_price(at_datetime=None):
        """Lấy giá đang hiệu lực tại thời điểm at_datetime"""
        if at_datetime is None:
            at_datetime = datetime.utcnow()
        from sqlalchemy import or_
        return FuelPrice.query.filter(
            FuelPrice.is_active == True,
            FuelPrice.effective_from <= at_datetime,
            or_(FuelPrice.effective_to >= at_datetime, FuelPrice.effective_to == None)
        ).order_by(FuelPrice.effective_from.desc()).first()
    
    def __repr__(self):
        fmt_from = self.effective_from.strftime('%d/%m/%Y %H:%M')
        if self.effective_to:
            fmt_to = self.effective_to.strftime('%d/%m/%Y %H:%M')
        else:
            fmt_to = 'hiện tại'
        return f'<FuelPrice {self.price_per_liter}đ/L ({fmt_from}→{fmt_to})>'

class FuelLog(db.Model):
    __tablename__ = 'fuel_logs'
    id = db.Column(db.Integer, primary_key=True)
    truck_id = db.Column(db.Integer, db.ForeignKey('trucks.id'), nullable=False)
    liters = db.Column(db.Numeric(12, 2), nullable=False)
    price_per_liter = db.Column(db.Numeric(12, 2), nullable=False)
    total_cost = db.Column(db.Numeric(12, 2), nullable=False)
    km_at_refuel = db.Column(db.Integer)
    refuel_date = db.Column(db.Date, nullable=False)
    is_substitute = db.Column(db.Boolean, default=False, comment='Tài xế đổ xăng cho xe không phải xe mặc định của mình (chạy giùm)')
    notes = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relations
    created_by = db.relationship('User', backref='fuel_logs')
    phois = db.relationship('Phoi', secondary=fuel_log_phois, backref='fuel_logs', lazy='dynamic')
    
    def attached_phoi_count(self):
        """Số phơi được gắn vào lần đổ xăng này"""
        return self.phois.count()
    
    def __repr__(self):
        return f'<FuelLog {self.liters}L on {self.refuel_date}>'

import logging

logger = logging.getLogger(__name__)


def seed_default_data():
    """Create default data if database is empty (kept for backward compatibility)."""
    if User.query.first() is not None:
        logger.info("Database already has data. Skipping seed.")
        return

    from flask import current_app
    current_app.logger.info("Seeding default data...")

    # ---- Users ----
    admin = User(
        username='admin',
        full_name='Quản trị viên',
        phone='0999999999',
        role='admin'
    )
    admin.set_password('admin123')
    db.session.add(admin)

    manager = User(
        username='manager',
        full_name='Quản lý',
        phone='0999999998',
        role='manager'
    )
    manager.set_password('manager123')
    db.session.add(manager)

    driver_sample = User(
        username='driver1',
        full_name='Tài xế Nguyễn Văn A',
        phone='0999999997',
        role='driver'
    )
    driver_sample.set_password('driver123')
    db.session.add(driver_sample)

    driver_nghia = User(
        username='trongnghia',
        full_name='Trọng Nghĩa',
        phone='0900000001',
        role='driver'
    )
    driver_nghia.set_password('driver123')
    db.session.add(driver_nghia)

    driver_tinh = User(
        username='tinhnv',
        full_name='Nguyễn Văn Tỉnh',
        phone='0900000002',
        role='driver'
    )
    driver_tinh.set_password('driver123')
    db.session.add(driver_tinh)

    db.session.flush()

    # ---- Trucks ----
    license_plates = [
        "71H02942", "71H00539", "71H02293", "71H02933", "71H00473", "71H00458",
        "71H00927", "71H00996", "71H02288", "71C07511", "71H01602", "71C01099",
        "71C08111", "71C03321", "71C08004", "71C05479", "71C01477", "71C01617",
        "71C02114", "71C03140", "71C02118", "71C00536", "71C08138", "71C03178",
        "71H02313", "71C03735", "71H00972", "71H00737", "71C05562", "71C03931",
        "71C09296", "71H00823", "71C04558", "71C04376", "71C03701", "71C04480",
        "71C03806", "71C04615", "71C07426", "71C08609", "71H01362"
    ]
    # Remove duplicates preserving order
    license_plates = list(dict.fromkeys(license_plates))

    for plate in license_plates:
        t = Truck(
            license_plate=plate,
            brand='Huyndai',
            capacity_ton=15.0,
            year=2020,
            fuel_rate=30.0,
            current_km=10000,
            status='available'
        )
        db.session.add(t)

    db.session.flush()

    # ---- Customers ----
    customers_data = [
        {
            'name': 'Dừa anh Dĩ',
            'cargo_type': 'Dừa',
            'default_origin': 'Bến Tre',
            'default_destination': 'Tây Ninh',
            'notes': 'Lên hàng dừa, full chuyến 3.600.000đ'
        },
        {
            'name': 'Lúa dì Giỏi',
            'cargo_type': 'Lúa',
            'default_origin': 'Tây Ninh',
            'default_destination': 'Bến Tre',
            'notes': 'Về lúa, full chuyến 4.000.000đ'
        },
        {
            'name': 'Lúa chị Thơ',
            'cargo_type': 'Lúa',
            'default_origin': 'Tây Ninh',
            'default_destination': 'Bến Tre',
            'notes': 'Giống lúa dì Giỏi, full chuyến 4.000.000đ'
        },
        {
            'name': 'Củi a Quẹo',
            'cargo_type': 'Củi',
            'default_origin': 'Tây Ninh',
            'default_destination': 'Bến Tre',
            'notes': 'Chở củi từ Tây Ninh về Bến Tre'
        }
    ]

    for cdata in customers_data:
        c = Customer(
            name=cdata['name'],
            cargo_type=cdata['cargo_type'],
            default_origin=cdata['default_origin'],
            default_destination=cdata['default_destination'],
            notes=cdata['notes'],
            created_by_id=admin.id
        )
        db.session.add(c)

    db.session.commit()
    current_app.logger.info(
        f"Seed data created: 5 users, {len(license_plates)} trucks, {len(customers_data)} customers"
    )
