import os
from datetime import timedelta

class Config:
    SESSION_TYPE = 'filesystem'
    SESSION_PERMANENT = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_USE_SIGNER = True
    SESSION_KEY_PREFIX = 'merged_dashboard:'
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-change-in-production'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or 'sqlite:///merged_dashboard.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    
    # API Keys - Set these via environment variables or replace with your keys
    AHREFS_TOKEN = os.environ.get('AHREFS_TOKEN') or 'your-ahrefs-api-token-here'
    AHREFS_BASE_URL = 'https://api.ahrefs.com/v3/site-explorer'
    HUNTER_API_KEY = os.environ.get('HUNTER_API_KEY') or 'your-hunter-api-key-here'
    HUNTER_BASE_URL = 'https://api.hunter.io/v2'
    
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None
    
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'

class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = True

class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
