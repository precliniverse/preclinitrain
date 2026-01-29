"""This module initializes the Flask application."""

import os
import importlib.resources
import logging
from logging.handlers import RotatingFileHandler, SMTPHandler
from datetime import datetime, timedelta, timezone
import click
from dotenv import load_dotenv
from flask import (
    Flask,
    request,
    g,
    current_app,
    session,
    redirect,
    url_for,
    render_template,
    flash,
    jsonify,
)
from flask.cli import with_appcontext
from flask_babel import Babel, lazy_gettext as _l
from flask_bootstrap import Bootstrap
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager, current_user
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, CSRFError

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login = LoginManager()
csrf = CSRFProtect()
login.login_view = 'auth.login'
login.login_message = _l('Please log in to access this page.')


@login.unauthorized_handler
def unauthorized():
    """Handle unauthorized access attempts."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': False, 'message': 'Unauthorized: Please log in.'}), 401
    return redirect(url_for('auth.login'))


babel = Babel()
mail = Mail()
bootstrap = Bootstrap()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)


# CLI Commands
@click.group()
def db_maintenance():
    """Database maintenance commands."""
    pass  # pylint: disable=unnecessary-pass


@db_maintenance.command()
@click.option('--dry-run', is_flag=True, help='Do not delete, just show what would be deleted.')
@with_appcontext
def clean_dismissed_notifications(dry_run):
    """Removes dismissed notifications older than 1 month."""
    # pylint: disable=import-outside-toplevel
    from app.models import UserDismissedNotification
    one_month_ago = datetime.now(timezone.utc) - timedelta(days=30)

    old_notifications = UserDismissedNotification.query.filter(
        UserDismissedNotification.dismissed_at < one_month_ago
    ).all()

    if not old_notifications:
        click.echo("No dismissed notifications older than 1 month found.")
        return

    if dry_run:
        click.echo(f"Dry run: Would delete {len(old_notifications)} dismissed notifications:")
        for notification in old_notifications:
            click.echo(
                f"  - ID: {notification.id}, Type: {notification.notification_type}, "
                f"Dismissed At: {notification.dismissed_at}"
            )
    else:
        for notification in old_notifications:
            db.session.delete(notification)
        db.session.commit()
        click.echo(
            f"Successfully deleted {len(old_notifications)} "
            "dismissed notifications older than 1 month."
        )


def get_locale():
    """Get the best matching language for the user."""
    if 'language' in session:
        return session['language']
    return request.accept_languages.best_match(current_app.config['LANGUAGES'])


# pylint: disable=too-many-locals,too-many-statements
def create_app(config_class=Config):
    """Create and configure the Flask application."""
    load_dotenv()  # Load environment variables
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    app.secret_key = app.config['SECRET_KEY']  # Explicitly set secret_key
    app.logger.setLevel(app.config['LOG_LEVEL'])  # Set logging level from config

    # Get version from VERSION file
    version_file = os.path.join(app.root_path, '..', 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, 'r', encoding='utf-8') as f:
            app.config['VERSION'] = f.read().strip()
    else:
        app.config['VERSION'] = '1.0.0'

    # Configure file logging
    if not os.path.exists('logs'):
        os.mkdir('logs')
    file_handler = RotatingFileHandler(
        'logs/preclinitrain.log', maxBytes=10240, backupCount=10
    )
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'))
    file_handler.setLevel(logging.DEBUG)
    app.logger.addHandler(file_handler)

    # Configure email logging for ERROR level
    if not app.debug and app.config.get('MAIL_ENABLED') and app.config['ADMINS']:
        auth = None
        if app.config['MAIL_USERNAME'] or app.config['MAIL_PASSWORD']:
            auth = (app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        secure = None
        if app.config['MAIL_USE_TLS']:
            secure = ()
        try:
            mail_handler = SMTPHandler(
                mailhost=(app.config['MAIL_SERVER'], app.config['MAIL_PORT']),
                fromaddr='no-reply@' + app.config['MAIL_SERVER'],
                toaddrs=app.config['ADMINS'], subject='PrecliniTrain Failure',
                credentials=auth, secure=secure)
            mail_handler.setLevel(logging.ERROR)
            app.logger.addHandler(mail_handler)
        except Exception as e:
            app.logger.warning(f"Could not initialize SMTP logging: {e}")

    # ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)
    csrf.init_app(app)
    babel.init_app(app, locale_selector=get_locale)
    mail.init_app(app)
    bootstrap.init_app(app)
    limiter.init_app(app)

    # Import models after db is initialized to avoid circular imports
    # pylint: disable=import-outside-toplevel
    from app.models import User, UserDismissedNotification, Skill, Role, Permission, \
        ContinuousTrainingEvent, UserContinuousTraining, ContinuousTrainingType, \
        UserContinuousTrainingStatus, InitialRegulatoryTrainingLevel, init_roles_and_permissions

    @app.context_processor
    def inject_api_key():
        if hasattr(current_user, 'api_key'):
            return dict(api_key=current_user.api_key)
        return dict(api_key=None)

    @app.context_processor
    def inject_version():
        return dict(app_version=current_app.config.get('VERSION', '1.0.0'))

    # Load models eagerly for context processor logic if needed, 
    # but we can import inside function to be safe.
    
    @app.before_request
    def load_current_facility():
        if current_user.is_authenticated:
            # Check if facility_id is in session
            facility_id = session.get('current_facility_id')
            
            # Import models here to avoid circular imports if any
            from app.models import Facility, UserFacilityRole
            
            if facility_id:
                # Verify user handles access to this facility
                # We check directly in DB to be secure
                ufr = UserFacilityRole.query.filter_by(
                    user_id=current_user.id, 
                    facility_id=facility_id,
                    is_approved=True
                ).first()
                
                if ufr:
                    g.current_facility = ufr.facility
                    g.current_role = ufr.role # Store current role for easy access
                else:
                    # Invalid facility in session (maybe access revoked), clear it
                    session.pop('current_facility_id', None)
                    g.current_facility = None
                    g.current_role = None
            else:
                 g.current_facility = None
                 g.current_role = None

            # If no current facility, try to set a default one
            if not g.current_facility:
                # Get the first approved facility
                first_ufr = UserFacilityRole.query.filter_by(
                    user_id=current_user.id,
                    is_approved=True
                ).first()
                if first_ufr:
                    session['current_facility_id'] = first_ufr.facility_id
                    g.current_facility = first_ufr.facility
                    g.current_role = first_ufr.role
        else:
            g.current_facility = None
            g.current_role = None

    @app.context_processor
    def inject_current_facility():
        return dict(
            current_facility=getattr(g, 'current_facility', None),
            current_role=getattr(g, 'current_role', None)
        )

    @app.template_filter('get_skill_name')
    def get_skill_name_filter(skill_id):
        try:
            skill = Skill.query.get(int(skill_id))
            return skill.name if skill else 'Unknown Skill'
        except (ValueError, TypeError):
            return 'Unknown Skill'

    # pylint: disable=import-outside-toplevel
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    # pylint: disable=import-outside-toplevel
    from app.root import bp as root_bp
    # pylint: disable=unused-import
    from app.root import routes
    app.register_blueprint(root_bp)

    # pylint: disable=import-outside-toplevel
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')

    # pylint: disable=import-outside-toplevel
    from app.team import bp as team_bp
    app.register_blueprint(team_bp, url_prefix='/team')

    # pylint: disable=import-outside-toplevel
    from app.training import bp as training_bp
    app.register_blueprint(training_bp, url_prefix='/training')

    # pylint: disable=import-outside-toplevel
    from app.api import bp as api_bp
    app.register_blueprint(api_bp, url_prefix='/api')
    csrf.exempt(api_bp)

    # pylint: disable=import-outside-toplevel
    from app.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')

    app.cli.add_command(db_maintenance)

    # Centralized Error Handlers
    @app.errorhandler(404)
    def not_found_error(_):
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Resource not found.'}), 404
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(_):
        db.session.rollback()
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Internal server error.'}), 500
        return render_template('errors/500.html'), 500

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        if request.method == 'POST' and request.path == url_for('auth.login'):
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()
            if user is None:
                flash('Invalid username or password', 'danger')
            else:
                flash('CSRF token missing or incorrect. Please try again.', 'danger')
            print(f"DEBUG: Flashed messages: {session.get('_flashes')}")
            return redirect(url_for('auth.login'))
        flash(e.description, 'danger')
        print(f"DEBUG: Flashed messages: {session.get('_flashes')}")
        return redirect(url_for('root.index'))

    with app.app_context():
        # pylint: disable=import-outside-toplevel
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        if not inspector.has_table("user"):
            db.create_all()
            print("Database tables created.")
            # pylint: disable=import-outside-toplevel
            # init_roles_and_permissions is already imported above
            init_roles_and_permissions()
            print("Roles and permissions initialized.")
        else:
            # pylint: disable=import-outside-toplevel
            # Role and init_roles_and_permissions are already imported above
            if not Role.query.filter_by(name='Admin').first():
                print("Admin role not found. Initializing roles and permissions.")
                init_roles_and_permissions()
                print("Roles and permissions initialized.")

        if User.query.first() is None:
            admin_email = os.environ.get('ADMIN_EMAIL')
            admin_password = os.environ.get('ADMIN_PASSWORD')
            if admin_email and admin_password:
                User.create_admin_user(admin_email, admin_password)
                print("Admin user created.")
            else:
                print("Admin user not created. ADMIN_EMAIL and ADMIN_PASSWORD not set.")

    return app