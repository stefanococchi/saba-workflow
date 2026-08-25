import os
from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from apscheduler.schedulers.background import BackgroundScheduler

# Base per models
Base = declarative_base()

# Sessione DB
db_session = None
scheduler = BackgroundScheduler()
limiter = Limiter(key_func=get_remote_address, default_limits=["200 per minute"])
_flask_app = None  # Cached Flask app instance for background threads


def init_db(app):
    """Inizializza database"""
    global db_session
    
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
        echo=app.config['SQLALCHEMY_ECHO'],
        pool_pre_ping=True,
    )
    
    db_session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )
    
    Base.query = db_session.query_property()
    Base.metadata.bind = engine
    
    return db_session


def create_app(config_object=None):
    """Factory pattern per creazione app Flask"""
    global _flask_app

    # Return cached app if already created (for background threads)
    if _flask_app is not None:
        return _flask_app

    app = Flask(__name__)
    
    # Configurazione
    if config_object is None:
        from config import get_config
        config_object = get_config()
    
    app.config.from_object(config_object)
    
    # Inizializza database
    init_db(app)
    
    # CORS — restrict to /api/* with configurable origins
    cors_origins = os.getenv('CORS_ORIGINS', '*').split(',')
    CORS(app, resources={r"/api/*": {"origins": cors_origins}})

    # Rate limiter
    limiter.init_app(app)

    # Security headers
    @app.after_request
    def _security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # Registra blueprints
    from app.api import workflow_bp, participant_bp, landing_bp, health_bp, admin_bp, landing_builder_api_bp, pratiche_bp
    from app.api.stripe_webhook import stripe_bp
    from app.api.auth import auth_bp, login_required, get_current_user
    app.register_blueprint(health_bp)
    app.register_blueprint(workflow_bp, url_prefix='/api')
    app.register_blueprint(participant_bp, url_prefix='/api')
    app.register_blueprint(landing_bp)
    app.register_blueprint(stripe_bp)
    # Protect admin routes with login (must be before register_blueprint)
    @admin_bp.before_request
    def require_login():
        from flask import session, redirect, url_for, g, request
        # Allow public access to uploaded images (logos on landing pages)
        if request.endpoint == 'admin.serve_image':
            return
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))
        g.user = get_current_user()
        if not g.user:
            session.clear()
            return redirect(url_for('auth.login'))
        # Client users cannot access admin — redirect to tracking/documents
        if session.get('role') == 'client':
            from app.api.auth import _client_landing_url
            return redirect(_client_landing_url(g.user))

    from app.api.tracking import tracking_bp
    app.register_blueprint(auth_bp)  # Auth (login/logout)
    app.register_blueprint(admin_bp)  # Admin interface
    app.register_blueprint(tracking_bp)  # Client tracking
    app.register_blueprint(landing_builder_api_bp, url_prefix='/api')  # Landing builder API
    app.register_blueprint(pratiche_bp, url_prefix='/api/ao')  # Pratiche documentali API
    
    # Avvia scheduler
    if not scheduler.running:
        scheduler.configure(timezone=app.config['SCHEDULER_TIMEZONE'])
        scheduler.start()

        # Cron job: controlla landing wait ogni 10 minuti
        from app.services.scheduler_service import SchedulerService
        def _landing_wait_cron():
            with app.app_context():
                SchedulerService.check_all_landing_waits()
        scheduler.add_job(_landing_wait_cron, 'interval', minutes=10,
                          id='landing_wait_cron', replace_existing=True)
    
    # Language switch route
    @app.route('/set-lang/<lang>')
    def set_language(lang):
        from flask import session, redirect, request as req
        if lang in ('it', 'en'):
            session['lang'] = lang
        return redirect(req.referrer or '/')

    # Inject translations into all templates
    @app.context_processor
    def inject_translations():
        from flask import session
        from app.translations import get_translations
        lang = session.get('lang', 'en')
        return {'t': get_translations(lang), 'current_lang': lang}

    # Filtro Jinja2 per convertire UTC → timezone locale
    import pytz
    local_tz = pytz.timezone(app.config.get('SCHEDULER_TIMEZONE', 'Europe/Rome'))

    @app.template_filter('localtime')
    def localtime_filter(dt, fmt='%d/%m/%Y %H:%M'):
        if dt is None:
            return ''
        utc_dt = pytz.utc.localize(dt)
        return utc_dt.astimezone(local_tz).strftime(fmt)

    # Teardown per chiudere sessioni
    @app.teardown_appcontext
    def shutdown_session(exception=None):
        if db_session:
            db_session.remove()
    
    # Context per CLI/migrations
    @app.shell_context_processor
    def make_shell_context():
        from app.models import Workflow, WorkflowStep, Participant, Execution
        return {
            'db_session': db_session,
            'Base': Base,
            'Workflow': Workflow,
            'WorkflowStep': WorkflowStep,
            'Participant': Participant,
            'Execution': Execution
        }
    
    _flask_app = app
    return app
