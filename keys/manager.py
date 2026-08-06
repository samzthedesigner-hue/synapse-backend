import sqlite3
import uuid
import hashlib
import secrets
from datetime import datetime, timedelta
from database.models import get_connection
import logging

logger = logging.getLogger(__name__)

class KeyManager:
    def create_key(self, name, token_limit=1000, request_limit=10000, expires_in_days=0):
        raw_key = f"syn_{secrets.token_hex(24)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_id = str(uuid.uuid4())[:8]

        expires_at = None
        if expires_in_days > 0:
            expires_at = (datetime.utcnow() + timedelta(days=expires_in_days)).isoformat()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO api_keys (id, key_hash, name, token_limit, request_limit, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (key_id, key_hash, name, token_limit, request_limit, expires_at))
        conn.commit()
        conn.close()

        return {
            'id': key_id,
            'raw_key': raw_key,
            'name': name,
            'token_limit': token_limit,
            'request_limit': request_limit,
            'expires_at': expires_at,
            'created_at': datetime.utcnow().isoformat()
        }

    def revoke_key(self, key_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE api_keys SET is_active = 0 WHERE id = ?', (key_id,))
        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def list_keys(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, key_hash, name, token_limit, request_limit,
                   tokens_used, requests_used, is_active, created_at,
                   last_used_at, expires_at
            FROM api_keys
            ORDER BY created_at DESC
        ''')
        rows = cursor.fetchall()
        conn.close()

        return [{
            'id': row[0],
            'key_masked': f"{row[1][:8]}...{row[1][-8:]}" if row[1] else 'N/A',
            'name': row[2],
            'token_limit': row[3],
            'request_limit': row[4],
            'tokens_used': row[5],
            'requests_used': row[6],
            'is_active': bool(row[7]),
            'created_at': row[8],
            'last_used_at': row[9],
            'expires_at': row[10],
            'tokens_remaining': row[3] - row[5],
            'requests_remaining': row[4] - row[6],
            'usage_percent': round((row[6] / row[4] * 100) if row[4] > 0 else 0, 1)
        } for row in rows]

    def get_key_info(self, key_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, key_hash, name, token_limit, request_limit,
                   tokens_used, requests_used, is_active, created_at,
                   last_used_at, expires_at
            FROM api_keys WHERE id = ?
        ''', (key_id,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'id': row[0],
            'key_masked': f"{row[1][:8]}...{row[1][-8:]}" if row[1] else 'N/A',
            'name': row[2],
            'token_limit': row[3],
            'request_limit': row[4],
            'tokens_used': row[5],
            'requests_used': row[6],
            'is_active': bool(row[7]),
            'created_at': row[8],
            'last_used_at': row[9],
            'expires_at': row[10],
            'tokens_remaining': row[3] - row[5],
            'requests_remaining': row[4] - row[6]
        }

    def get_key_info_by_hash(self, key_hash):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, token_limit, request_limit, tokens_used,
                   requests_used, is_active, expires_at
            FROM api_keys WHERE key_hash = ?
        ''', (key_hash,))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        return {
            'id': row[0],
            'name': row[1],
            'token_limit': row[2],
            'request_limit': row[3],
            'tokens_used': row[4],
            'requests_used': row[5],
            'is_active': bool(row[6]),
            'expires_at': row[7]
        }

    def increment_requests(self, key_hash):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE api_keys
            SET requests_used = requests_used + 1,
                last_used_at = ?
            WHERE key_hash = ?
        ''', (datetime.utcnow().isoformat(), key_hash))
        conn.commit()
        conn.close()

    def increment_tokens(self, key_hash, tokens):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE api_keys
            SET tokens_used = tokens_used + ?
            WHERE key_hash = ?
        ''', (tokens, key_hash))
        conn.commit()
        conn.close()

    def update_limits(self, key_id, token_limit=None, request_limit=None):
        conn = get_connection()
        cursor = conn.cursor()

        if token_limit is not None:
            cursor.execute('UPDATE api_keys SET token_limit = ? WHERE id = ?', (token_limit, key_id))
        if request_limit is not None:
            cursor.execute('UPDATE api_keys SET request_limit = ? WHERE id = ?', (request_limit, key_id))

        affected = cursor.rowcount
        conn.commit()
        conn.close()
        return affected > 0

    def deactivate_expired_keys(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE api_keys SET is_active = 0
            WHERE expires_at IS NOT NULL
            AND datetime(expires_at) < datetime('now')
            AND is_active = 1
        ''')
        count = cursor.rowcount
        conn.commit()
        conn.close()
        return count

    def get_stats(self):
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT
                COUNT(*) as total_keys,
                SUM(CASE WHEN is_active = 1 THEN 1 ELSE 0 END) as active_keys,
                SUM(CASE WHEN is_active = 0 THEN 1 ELSE 0 END) as revoked_keys,
                SUM(requests_used) as total_requests,
                SUM(tokens_used) as total_tokens
            FROM api_keys
        ''')

        row = cursor.fetchone()
        conn.close()

        return {
            'total_keys': row[0] or 0,
            'active_keys': row[1] or 0,
            'revoked_keys': row[2] or 0,
            'total_requests': row[3] or 0,
            'total_tokens': row[4] or 0
        }
