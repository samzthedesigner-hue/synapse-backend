import sqlite3
import os
from config import Config

def get_connection():
    db_path = Config.DATABASE_PATH
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else '.', exist_ok=True)
    return sqlite3.connect(db_path)

def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS knowledge (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            content_type TEXT DEFAULT 'text',
            metadata TEXT DEFAULT '{}',
            embedding BLOB,
            topic TEXT DEFAULT 'general',
            source TEXT DEFAULT 'unknown',
            trust_score REAL DEFAULT 0.5,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            access_count INTEGER DEFAULT 0
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            key_hash TEXT UNIQUE NOT NULL,
            name TEXT DEFAULT 'Unnamed Key',
            token_limit INTEGER DEFAULT 1000,
            request_limit INTEGER DEFAULT 10000,
            tokens_used INTEGER DEFAULT 0,
            requests_used INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_used_at TIMESTAMP,
            expires_at TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS backup_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            items_backed_up INTEGER,
            size_bytes INTEGER,
            error_message TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS search_cache (
            query_hash TEXT PRIMARY KEY,
            query TEXT,
            results TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hit_count INTEGER DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS source_reputation (
            source TEXT PRIMARY KEY,
            trust_score REAL DEFAULT 0.5,
            total_submissions INTEGER DEFAULT 0,
            flagged_submissions INTEGER DEFAULT 0,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_type ON knowledge(content_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_source ON knowledge(source)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_trust ON knowledge(trust_score)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge(created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_api_keys_active ON api_keys(is_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_source_reputation_score ON source_reputation(trust_score)')

    conn.commit()
    conn.close()

init_database()
