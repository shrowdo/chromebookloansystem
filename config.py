import os

class Config:
    # Common configurations
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'default_secret_key'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

class DevelopmentConfig(Config):
    # Development-specific configurations
    DEBUG = True
    # Replace with your local PostgreSQL settings
    SQLALCHEMY_DATABASE_URI = 'postgresql://your_username:your_password@localhost:5432/your_database_name'

class ProductionConfig(Config):
    # Production-specific configurations
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'postgresql://fallback_user:fallback_password@localhost:5432/fallback_database')
