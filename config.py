import os

class Config:
    # Flask
    SECRET_KEY = os.environ.get('SECRET_KEY', 'synapse-dev-key-change-in-production')

    # Internal communication (NeuralForge ↔ Synapse)
    INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', 'synapse-internal-change-me')

    # Admin access (for dashboard and key management)
    ADMIN_SECRET = os.environ.get('ADMIN_SECRET', 'admin-secret-change-me')

    # Database
    DATABASE_PATH = os.environ.get('DATABASE_PATH', '/tmp/synapse_knowledge.db')

    # File Storage Paths
    STORAGE_TEXT = os.environ.get('STORAGE_TEXT', '/tmp/synapse_storage/text')
    STORAGE_IMAGES = os.environ.get('STORAGE_IMAGES', '/tmp/synapse_storage/images')
    STORAGE_VIDEOS = os.environ.get('STORAGE_VIDEOS', '/tmp/synapse_storage/videos')
    STORAGE_AUDIO = os.environ.get('STORAGE_AUDIO', '/tmp/synapse_storage/audio')
    STORAGE_OTHER = os.environ.get('STORAGE_OTHER', '/tmp/synapse_storage/other')

    # Max storage per type (in GB) — massive limits
    MAX_STORAGE_TEXT = int(os.environ.get('MAX_STORAGE_TEXT', 50))
    MAX_STORAGE_IMAGES = int(os.environ.get('MAX_STORAGE_IMAGES', 100))
    MAX_STORAGE_VIDEOS = int(os.environ.get('MAX_STORAGE_VIDEOS', 500))
    MAX_STORAGE_AUDIO = int(os.environ.get('MAX_STORAGE_AUDIO', 100))
    MAX_STORAGE_OTHER = int(os.environ.get('MAX_STORAGE_OTHER', 100))

    # Search
    EMBEDDING_MODEL = 'all-MiniLM-L6-v2'
    MAX_SEARCH_RESULTS = 100

    # Content Limits
    MAX_CONTENT_LENGTH = 50000
    MAX_FILE_SIZE_MB = 5000  # 5GB per file max

    # Rate Limiting
    RATE_LIMIT_REQUESTS = 60
    RATE_LIMIT_WINDOW = 60

    # API Key defaults
    DEFAULT_TOKEN_LIMIT = 1000
    DEFAULT_REQUEST_LIMIT = 10000
    DEFAULT_KEY_EXPIRY_DAYS = 0
