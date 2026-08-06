import sqlite3
import json
import uuid
from datetime import datetime
from sentence_transformers import SentenceTransformer
import numpy as np
from config import Config
from database.models import get_connection
from utils.text_processor import extract_topics, calculate_trust_score
import logging

logger = logging.getLogger(__name__)

class DataStore:
    def __init__(self):
        self.model = None
        self._init_source_reputation()

    def _load_model(self):
        if self.model is None:
            logger.info("Loading embedding model...")
            self.model = SentenceTransformer(Config.EMBEDDING_MODEL)
            logger.info("Embedding model loaded")

    def _init_source_reputation(self):
        trusted_sources = [
            'wikipedia.org',
            'arxiv.org',
            'stackexchange.com',
            'github.com',
            'docs.python.org'
        ]
        conn = get_connection()
        cursor = conn.cursor()
        for source in trusted_sources:
            cursor.execute('''
                INSERT OR IGNORE INTO source_reputation (source, trust_score)
                VALUES (?, 0.8)
            ''', (source,))
        conn.commit()
        conn.close()

    def save(self, content, content_type='text', metadata=None):
        self._load_model()
        knowledge_id = str(uuid.uuid4())
        content_for_embedding = content[:5000] if len(content) > 5000 else content
        embedding = self.model.encode([content_for_embedding])[0]
        embedding_bytes = embedding.tobytes()
        if metadata is None:
            metadata = {}
        topic = metadata.get('topic', extract_topics(content))
        source = metadata.get('source', 'direct_input')
        trust_score = calculate_trust_score(source, content, metadata)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO knowledge
            (id, content, content_type, metadata, embedding, topic, source, trust_score, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            knowledge_id,
            content,
            content_type,
            json.dumps(metadata),
            embedding_bytes,
            topic,
            source,
            trust_score,
            datetime.now().isoformat()
        ))

        cursor.execute('''
            INSERT INTO source_reputation (source, total_submissions, first_seen, last_seen)
            VALUES (?, 1, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                total_submissions = total_submissions + 1,
                last_seen = ?
        ''', (source, datetime.now().isoformat(), datetime.now().isoformat(), datetime.now().isoformat()))

        conn.commit()
        conn.close()

        logger.info(f"Stored: {knowledge_id} [{content_type}] topic={topic} trust={trust_score:.2f}")
        return knowledge_id

    def get_by_topic(self, topic, limit=50):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, content, content_type, metadata, source, trust_score, created_at, access_count
            FROM knowledge
            WHERE topic = ?
            ORDER BY trust_score DESC, created_at DESC
            LIMIT ?
        ''', (topic, limit))
        rows = cursor.fetchall()

        ids = [row[0] for row in rows]
        if ids:
            placeholders = ','.join(['?' for _ in ids])
            cursor.execute(f'''
                UPDATE knowledge
                SET accessed_at = ?, access_count = access_count + 1
                WHERE id IN ({placeholders})
            ''', [datetime.now().isoformat()] + ids)
            conn.commit()

        conn.close()

        return [{
            'id': row[0],
            'content': row[1],
            'type': row[2],
            'metadata': json.loads(row[3]) if row[3] else {},
            'source': row[4],
            'trust_score': row[5],
            'created_at': row[6],
            'access_count': row[7]
        } for row in rows]

    def get_by_id(self, knowledge_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, content, content_type, metadata, source, trust_score, created_at, access_count
            FROM knowledge
            WHERE id = ?
        ''', (knowledge_id,))
        row = cursor.fetchone()

        if row:
            cursor.execute('''
                UPDATE knowledge
                SET accessed_at = ?, access_count = access_count + 1
                WHERE id = ?
            ''', (datetime.now().isoformat(), knowledge_id))
            conn.commit()

        conn.close()

        if not row:
            return None

        return {
            'id': row[0],
            'content': row[1],
            'type': row[2],
            'metadata': json.loads(row[3]) if row[3] else {},
            'source': row[4],
            'trust_score': row[5],
            'created_at': row[6],
            'access_count': row[7]
        }

    def delete(self, knowledge_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
        conn.commit()
        conn.close()
        logger.info(f"Deleted: {knowledge_id}")

    def get_stats(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                COUNT(*) as total_items,
                COUNT(DISTINCT topic) as total_topics,
                COUNT(DISTINCT source) as total_sources,
                AVG(trust_score) as avg_trust,
                SUM(CASE WHEN content_type = 'text' THEN 1 ELSE 0 END) as text_count,
                SUM(CASE WHEN content_type = 'image' THEN 1 ELSE 0 END) as image_count,
                SUM(CASE WHEN content_type = 'video' THEN 1 ELSE 0 END) as video_count,
                SUM(LENGTH(content)) as total_bytes
            FROM knowledge
        ''')
        row = cursor.fetchone()
        conn.close()

        return {
            'total_items': row[0] or 0,
            'total_topics': row[1] or 0,
            'total_sources': row[2] or 0,
            'avg_trust_score': round(row[3] or 0, 2),
            'text_count': row[4] or 0,
            'image_count': row[5] or 0,
            'video_count': row[6] or 0,
            'total_bytes': row[7] or 0,
            'total_mb': round((row[7] or 0) / (1024 * 1024), 2)
        }

    def get_all_for_backup(self):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM knowledge')
        rows = cursor.fetchall()
        conn.close()

        return [
            {
                'id': row[0],
                'content': row[1],
                'content_type': row[2],
                'metadata': row[3],
                'embedding': row[4].hex() if row[4] else None,
                'topic': row[5],
                'source': row[6],
                'trust_score': row[7],
                'created_at': row[8],
                'updated_at': row[9],
                'accessed_at': row[10],
                'access_count': row[11]
            }
            for row in rows
        ]

    def restore_from_backup(self, data):
        conn = get_connection()
        cursor = conn.cursor()
        count = 0
        for item in data:
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO knowledge
                    (id, content, content_type, metadata, embedding, topic, source, trust_score,
                     created_at, updated_at, accessed_at, access_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    item['id'],
                    item['content'],
                    item.get('content_type', 'text'),
                    item.get('metadata', '{}'),
                    bytes.fromhex(item['embedding']) if item.get('embedding') else None,
                    item.get('topic', 'general'),
                    item.get('source', 'unknown'),
                    item.get('trust_score', 0.5),
                    item.get('created_at', datetime.now().isoformat()),
                    item.get('updated_at', datetime.now().isoformat()),
                    item.get('accessed_at', datetime.now().isoformat()),
                    item.get('access_count', 0)
                ))
                count += 1
            except Exception as e:
                logger.error(f"Failed to restore item {item.get('id')}: {e}")

        conn.commit()
        conn.close()
        logger.info(f"Restored {count} items from backup")
        return count
