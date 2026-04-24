from flask import Flask
from flask_cors import CORS
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker, declarative_base
from apscheduler.schedulers.background import BackgroundScheduler
from concurrent.futures import ThreadPoolExecutor

# Base per models
Base = declarative_base()

# Sessione DB
db_session = None
# Limita a 5 thread concorrenti per evitare sovraccarico su Graph API e DB
scheduler = BackgroundScheduler(executors={
    'default': ThreadPoolExecutor(max_workers=5)
})


def init_db(app):
    """Inizializza database"""
    global db_session
    
    engine = create_engine(
        app.config['SQLALCHEMY_DATABASE_URI'],
        echo=app.config['SQLALCHEMY_ECHO'],
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=300
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
    from app.api import workflow_bp, participant_bp, landing_bp, health_bp
    app.register_blueprint(health_bp)
    app.register_blueprint(workflow_bp, url_prefix='/api')
    app.register_blueprint(participant_bp, url_prefix='/api')
    app.register_blueprint(landing_bp)
    
    # Avvia scheduler
    if not scheduler.running:
        scheduler.configure(timezone=app.config['SCHEDULER_TIMEZONE'])
        scheduler.start()
    
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
