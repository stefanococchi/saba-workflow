import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configurazione base"""
    
    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/saba_workflow'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG
    
    # SMTP
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', '')
    SMTP_USE_TLS = os.getenv('SMTP_USE_TLS', 'True').lower() == 'true'
    SMTP_FROM_EMAIL = os.getenv('SMTP_FROM_EMAIL', SMTP_USER)
    SMTP_FROM_NAME = os.getenv('SMTP_FROM_NAME', 'Saba Workflow')
    
    # JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_EXPIRATION_HOURS = int(os.getenv('JWT_EXPIRATION_HOURS', 72))
    
    # Scheduler
    SCHEDULER_API_ENABLED = True
    SCHEDULER_TIMEZONE = 'Europe/Rome'
    
    # Landing page URL base
    LANDING_BASE_URL = os.getenv('LANDING_BASE_URL', 'http://localhost:5001/landing')

    # Saba Form DB (read-only, per import partecipanti)
    SABAFORM_DATABASE_URI = os.getenv(
        'SABAFORM_DATABASE_URL',
        'postgresql://postgres:123456@localhost:5432/sabaform'
    )


class DevelopmentConfig(Config):
    """Configurazione sviluppo"""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Configurazione produzione"""
    DEBUG = False
    TESTING = False


class TestingConfig(Config):
    """Configurazione testing"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'


# Mappa configurazioni
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Ritorna configurazione in base a ENV"""
    env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
