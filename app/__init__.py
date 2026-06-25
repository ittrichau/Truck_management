import os
import logging
from logging.handlers import RotatingFileHandler

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from config import get_config

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def create_app(config_name=None):
    """Flask app factory."""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(get_config())
    app.config['ENV'] = config_name

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Vui lòng đăng nhập để tiếp tục.'
    login_manager.login_message_category = 'warning'

    # Configure logging
    _configure_logging(app)

    # Register blueprints
    from app.routes.auth import bp as auth_bp
    from app.routes.trucks import bp as trucks_bp
    from app.routes.customers import bp as customers_bp
    from app.routes.phoi import bp as phoi_bp
    from app.routes.fuel import bp as fuel_bp
    from app.routes.drivers import bp as drivers_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(trucks_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(phoi_bp)
    app.register_blueprint(fuel_bp)
    app.register_blueprint(drivers_bp)

    # Register CLI commands
    from app.cli import register_cli_commands
    register_cli_commands(app)

    # Health check endpoint (unauthenticated, for container orchestration)
    @app.route('/health')
    def health_check():
        try:
            db.session.execute(text('SELECT 1'))
            return jsonify({'status': 'ok', 'db': 'ok'}), 200
        except Exception:
            return jsonify({'status': 'error', 'db': 'unreachable'}), 503

    # Context processors
    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        return dict(current_user=current_user)

    # Apply any pending migrations (tables created via Alembic, not db.create_all)
    with app.app_context():
        from app import models  # noqa: F401
        from flask_migrate import upgrade as _migrate_upgrade
        _migrate_upgrade()

        # Auto-seed only in development
        if app.config.get('SEED_ON_STARTUP', False):
            models.seed_default_data()

    return app


def _configure_logging(app):
    """Setup rotating file handler + console handler."""
    log_level = getattr(logging, app.config.get('LOG_LEVEL', 'INFO').upper(), logging.INFO)

    # Ensure log directory exists
    log_file = app.config.get('LOG_FILE', 'logs/app.log')
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError:
            # Cannot create log dir — fall back to console only
            log_file = None

    # Console handler always present
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    ))
    app.logger.addHandler(console_handler)

    # File handler (if log dir writable)
    if log_file:
        try:
            file_handler = RotatingFileHandler(
                log_file, maxBytes=10 * 1024 * 1024, backupCount=5
            )
            file_handler.setLevel(log_level)
            file_handler.setFormatter(logging.Formatter(
                '%(asctime)s %(levelname)s [%(module)s]: %(message)s'
            ))
            app.logger.addHandler(file_handler)
        except OSError:
            pass  # File logging unavailable — continue with console only

    app.logger.setLevel(log_level)
    app.logger.info(f'App started (env={app.config.get("ENV", "unknown")})')