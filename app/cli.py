"""CLI commands for Truck Management."""
import click
from flask import current_app
from flask.cli import with_appcontext


def register_cli_commands(app):
    """Register custom Flask CLI commands."""

    @app.cli.command('seed-data')
    @with_appcontext
    def seed_data_command():
        """Seed database with default data (users, trucks, customers)."""
        from app import db
        from app.models import User, Truck, Customer

        if User.query.first() is not None:
            click.echo('Database already has data. Skipping seed.')
            return

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
        click.echo('Seed data created successfully!')
        click.echo(f'  Users: 5 (admin, manager, driver1, trongnghia, tinhnv)')
        click.echo(f'  Trucks: {len(license_plates)}')
        click.echo(f'  Customers: {len(customers_data)}')

    @app.cli.command('create-admin')
    @click.option('--username', default='admin', show_default=True, prompt=True,
                  help='Tên đăng nhập của tài khoản quản trị.')
    @click.option('--full-name', prompt=True, help='Họ tên hiển thị.')
    @click.option('--phone', default='', help='Số điện thoại (không bắt buộc).')
    @click.password_option(confirmation_prompt=True,
                           help='Mật khẩu mới cho tài khoản quản trị.')
    @click.option('--update/--no-update', default=False,
                  help='Cho phép cập nhật tài khoản nếu tên đăng nhập đã tồn tại.')
    @with_appcontext
    def create_admin_command(username, full_name, phone, password, update):
        """Create a permanent administrator account without demo credentials."""
        from app import db
        from app.models import User

        username = username.strip()
        full_name = full_name.strip()
        if not username or not full_name:
            raise click.UsageError('Tên đăng nhập và họ tên không được để trống.')
        if len(password) < 12:
            raise click.UsageError('Mật khẩu phải có ít nhất 12 ký tự.')

        user = User.query.filter_by(username=username).first()
        if user:
            if not update:
                raise click.UsageError(
                    'Tài khoản đã tồn tại. Chạy lại với --update để thay đổi mật khẩu/thông tin.'
                )
            user.full_name = full_name
            user.phone = phone.strip() or None
            user.role = 'admin'
            user.is_active = True
            user.set_password(password)
            action = 'Đã cập nhật'
        else:
            user = User(
                username=username,
                full_name=full_name,
                phone=phone.strip() or None,
                role='admin',
                is_active=True,
            )
            user.set_password(password)
            db.session.add(user)
            action = 'Đã tạo'

        db.session.commit()
        click.echo(f'{action} tài khoản quản trị: {user.username}')

    @app.cli.command('health')
    @with_appcontext
    def health_command():
        """Basic health check via CLI."""
        try:
            from app.models import User
            user_count = User.query.count()
            click.echo(f'OK — DB accessible, {user_count} users')
        except Exception as e:
            click.echo(f'ERROR: {e}', err=True)