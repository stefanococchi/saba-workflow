from flask import Flask
from flask_cors import CORS
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from apscheduler.schedulers.background import BackgroundScheduler

# Base per models
Base = declarative_base()

# Sessione DB
db_session = None
scheduler = BackgroundScheduler()


def init_db(app):
    """Inizializza database"""
    global db_session
    
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
        echo=app.config['SQLALCHEMY_ECHO']
    )
    
    db_session = scoped_session(
        sessionmaker(autocommit=False, autoflush=False, bind=engine)
    )
    
    Base.query = db_session.query_property()
    Base.metadata.bind = engine
    
    return db_session


def create_app(config_object=None):
    """Factory pattern per creazione app Flask"""
    
    app = Flask(__name__)
    
    # Configurazione
    if config_object is None:
        from config import get_config
        config_object = get_config()
    
    app.config.from_object(config_object)
    
    # Inizializza database
    init_db(app)
    
    # CORS
    CORS(app)
    
    # Registra blueprints
    from app.api import workflow_bp, participant_bp, landing_bp, health_bp, admin_bp, landing_builder_api_bp
    from app.api.auth import auth_bp, login_required, get_current_user
    app.register_blueprint(health_bp)
    app.register_blueprint(workflow_bp, url_prefix='/api')
    app.register_blueprint(participant_bp, url_prefix='/api')
    app.register_blueprint(landing_bp)
    # Protect admin routes with login (must be before register_blueprint)
    @admin_bp.before_request
    def require_login():
        from flask import session, redirect, url_for, g
        if not session.get('user_id'):
            return redirect(url_for('auth.login'))
        g.user = get_current_user()
        if not g.user:
            session.clear()
            return redirect(url_for('auth.login'))

    app.register_blueprint(auth_bp)  # Auth (login/logout)
    app.register_blueprint(admin_bp)  # Admin interface
    app.register_blueprint(landing_builder_api_bp, url_prefix='/api')  # Landing builder API
    
    # Avvia scheduler
    if not scheduler.running:
        scheduler.configure(timezone=app.config['SCHEDULER_TIMEZONE'])
        scheduler.start()
    
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
    
    return app
