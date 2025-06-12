import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or '5dJcmv1vX4mSQEQh6RSXlccV2jukwLiW'
    
    # PostgreSQL Configuration
    DATABASE_URL = os.environ.get('DATABASE_URL') or \
        'postgresql://postgres:d7tm3YJJJ7RHVgovPtFzwhK4TsrSbOpT@db:5432/scheduling_db'
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    
    # File upload configuration
    UPLOAD_FOLDER = 'app/static/uploads'
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    
    # Email configuration - Will be dynamically set from database
    # These are defaults that can be overridden by admin settings
    MAIL_SERVER = None
    MAIL_PORT = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = None
    MAIL_PASSWORD = None
    MAIL_DEFAULT_SENDER = None
    
    # Pagination
    SHIFTS_PER_PAGE = 20

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False
    # Production PostgreSQL URL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'postgresql://postgres:d7tm3YJJJ7RHVgovPtFzwhK4TsrSbOpT@db:5432/scheduling_db'

config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
