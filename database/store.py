import sqlite3
import json
import uuid
import os
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
        self._init_storage_dirs()

    def _load_model(self):
        if self.model is None:
            logger.info("Loading embedding model...")
            self.model = SentenceTransformer(Config.EMBEDDING_MODEL)
            logger.info("Embedding model loaded")

    def _init_storage_dirs(self):
        """Create storage directories for all file types"""
        dirs = [
            Config.STORAGE_TEXT,
            Config.STORAGE_IMAGES,
            Config.STORAGE_VIDEOS,
            Config.STORAGE_AUDIO,
            Config.STORAGE_OTHER
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)

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

    def _get_storage_dir(self, content_type):
        """Get the storage directory for a content type"""
        mapping = {
            'text': Config.STORAGE_TEXT,
            'image': Config.STORAGE_IMAGES,
            'video': Config.STORAGE_VIDEOS,
            'audio': Config.STORAGE_AUDIO
        }
        return mapping.get(content_type, Config.STORAGE_OTHER)

    def _get_max_storage(self, content_type):
        """Get max storage limit for a content type in bytes"""
        mapping = {
            'text': Config.MAX_STORAGE_TEXT * 1024 * 1024 * 1024,
            'image': Config.MAX_STORAGE_IMAGES * 1024 * 1024 * 1024,
            'video': Config.MAX_STORAGE_VIDEOS * 1024 * 1024 * 1024,
            'audio': Config.MAX_STORAGE_AUDIO * 1024 * 1024 * 1024
        }
        return mapping.get(content_type, Config.MAX_STORAGE_OTHER * 1024 * 1024 * 1024)

    def _check_storage_limit(self, content_type, new_size):
        """Check if adding new file would exceed storage limit"""
        storage_dir = self._get_storage_dir(content_type)
        current_size = 0
        if os.path.exists(storage_dir):
            for dirpath, dirnames, filenames in os.walk(storage_dir):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        current_size += os.path.getsize(fp)
                    except OSError:
                        pass

        max_size = self._get_max_storage(content_type)
        if current_size + new_size > max_size:
            return False, current_size, max_size
        return True, current_size, max_size

    def save(self, content, content_type='text', metadata=None, file_data=None, file_extension=None):
        """
        Store knowledge item.
        For text: content is the text itself, stored in DB.
        For images/videos/audio: content is description, file_data stored as file.
        """
        self._load_model()
        knowledge_id = str(uuid.uuid4())

        if metadata is None:
            metadata = {}

        file_path = None
        file_size = 0

        # Handle file types (not plain text)
        if content_type in ['image', 'video', 'audio'] and file_data:
            file_extension = file_extension or 'bin'
            storage_dir = self._get_storage_dir(content_type)

            # Create subdirectory organized by date
            date_dir = datetime.now().strftime('%Y/%m/%d')
            full_dir = os.path.join(storage_dir, date_dir)
            os.makedirs(full_dir, exist_ok=True)

            # Save file
            file_name = f"{knowledge_id}.{file_extension}"
            file_path = os.path.join(full_dir, file_name)

            # file_data can be bytes or base64 string
            if isinstance(file_data, str):
                import base64
                file_data = base64.b64decode(file_data)

            file_size = len(file_data)

            # Check storage limit
            can_store, current, max_size = self._check_storage_limit(content_type, file_size)
            if not can_store:
                logger.warning(
                    f"Storage limit reached for {content_type}: "
                    f"{current / (1024**3):.1f}GB / {max_size / (1024**3):.1f}GB"
                )
                return None

            with open(file_path, 'wb') as f:
                f.write(file_data)

            metadata['file_path'] = file_path
            metadata['file_size'] = file_size
            metadata['file_extension'] = file_extension

        # Generate embedding from content text
        content_for_embedding = content[:5000] if len(content) > 5000 else content
        embedding = self.model.encode([content_for_embedding])[0]
        embedding_bytes = embedding.tobytes()

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

        # Update source reputation
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

        results = []
        for row in rows:
            metadata = json.loads(row[3]) if row[3] else {}
            item = {
                'id': row[0],
                'content': row[1],
                'type': row[2],
                'metadata': metadata,
                'source': row[4],
                'trust_score': row[5],
                'created_at': row[6],
                'access_count': row[7]
            }
            if metadata.get('file_path'):
                item['file_path'] = metadata['file_path']
                item['file_size'] = metadata.get('file_size', 0)
            results.append(item)

        return results

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

        metadata = json.loads(row[3]) if row[3] else {}
        return {
            'id': row[0],
            'content': row[1],
            'type': row[2],
            'metadata': metadata,
            'source': row[4],
            'trust_score': row[5],
            'created_at': row[6],
            'access_count': row[7],
            'file_path': metadata.get('file_path'),
            'file_size': metadata.get('file_size', 0)
        }

    def get_file(self, knowledge_id):
        """Retrieve the actual file for a stored item"""
        item = self.get_by_id(knowledge_id)
        if not item or not item.get('file_path'):
            return None, None

        file_path = item['file_path']
        if not os.path.exists(file_path):
            return None, None

        with open(file_path, 'rb') as f:
            file_data = f.read()

        file_extension = item['metadata'].get('file_extension', 'bin')
        return file_data, file_extension

    def delete(self, knowledge_id):
        """Delete knowledge item and its associated file"""
        item = self.get_by_id(knowledge_id)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM knowledge WHERE id = ?", (knowledge_id,))
        conn.commit()
        conn.close()

        if item and item.get('file_path') and os.path.exists(item['file_path']):
            os.remove(item['file_path'])
            logger.info(f"Deleted file: {item['file_path']}")

        logger.info(f"Deleted: {knowledge_id}")

    def get_stats(self):
        """Get comprehensive storage statistics"""
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
                SUM(CASE WHEN content_type = 'audio' THEN 1 ELSE 0 END) as audio_count,
                SUM(LENGTH(content)) as content_bytes
            FROM knowledge
        ''')
        row = cursor.fetchone()
        conn.close()

        # Calculate file storage sizes
        file_sizes = {}
        for ftype, path in [
            ('text', Config.STORAGE_TEXT),
            ('images', Config.STORAGE_IMAGES),
            ('videos', Config.STORAGE_VIDEOS),
            ('audio', Config.STORAGE_AUDIO),
            ('other', Config.STORAGE_OTHER)
        ]:
            total = 0
            if os.path.exists(path):
                for dirpath, dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        try:
                            total += os.path.getsize(fp)
                        except OSError:
                            pass
            file_sizes[ftype] = total

        return {
            'total_items': row[0] or 0,
            'total_topics': row[1] or 0,
            'total_sources': row[2] or 0,
            'avg_trust_score': round(row[3] or 0, 2),
            'text_count': row[4] or 0,
            'image_count': row[5] or 0,
            'video_count': row[6] or 0,
            'audio_count': row[7] or 0,
            'content_bytes': row[8] or 0,
            'content_gb': round((row[8] or 0) / (1024**3), 4),
            'file_storage': {
                'text_gb': round(file_sizes.get('text', 0) / (1024**3), 4),
                'images_gb': round(file_sizes.get('images', 0) / (1024**3), 4),
                'videos_gb': round(file_sizes.get('videos', 0) / (1024**3), 4),
                'audio_gb': round(file_sizes.get('audio', 0) / (1024**3), 4),
                'other_gb': round(file_sizes.get('other', 0) / (1024**3), 4),
                'total_gb': round(sum(file_sizes.values()) / (1024**3), 4)
            },
            'storage_limits': {
                'text_gb': Config.MAX_STORAGE_TEXT,
                'images_gb': Config.MAX_STORAGE_IMAGES,
                'videos_gb': Config.MAX_STORAGE_VIDEOS,
                'audio_gb': Config.MAX_STORAGE_AUDIO,
                'other_gb': Config.MAX_STORAGE_OTHER
            }
        }
