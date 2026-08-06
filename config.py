import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'synapse-dev-key-change-in-production')
    INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', 'synapse-internal-change-me')
    ADMIN_SECRET = os.environ.get('ADMIN_SECRET', 'admin-secret-change-me')
    DATABASE_PATH = os.environ.get('DATABASE_PATH', '/tmp/synapse_knowledge.db')
    GOOGLE_DRIVE_ENABLED = os.environ.get('GOOGLE_DRIVE_ENABLED', 'true').lower() == 'true'
    GOOGLE_DRIVE_FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID', '')
    GOOGLE_DRIVE_CREDENTIALS = os.environ.get('GOOGLE_DRIVE_CREDENTIALS', '')
    VALID_API_KEYS = os.environ.get('VALID_API_KEYS', '').split(',') if os.environ.get('VALID_API_KEYS') else []
    EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
    MAX_SEARCH_RESULTS = 100
    MAX_CONTENT_LENGTH = 50000
    MAX_FILE_SIZE_MB = 50
    BACKUP_INTERVAL_HOURS = 6
    RATE_LIMIT_REQUESTS = 60
    RATE_LIMIT_WINDOW = 60
    DEFAULT_TOKEN_LIMIT = 1000
    DEFAULT_REQUEST_LIMIT = 10000
    DEFAULT_KEY_EXPIRY_DAYS = 0
