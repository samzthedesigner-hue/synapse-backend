import numpy as np
from sentence_transformers import SentenceTransformer
from database.models import get_connection
from config import Config
import logging
import hashlib
import json
from datetime import datetime

logger = logging.getLogger(__name__)

class SearchEngine:
    def __init__(self):
        self.model = None

    def _load_model(self):
        if self.model is None:
            logger.info("Loading embedding model for search...")
            self.model = SentenceTransformer(Config.EMBEDDING_MODEL)

    def search(self, query, search_type='all', limit=20):
        """Semantic search across knowledge base with trust score weighting"""
        self._load_model()

        # Check cache
        cached = self._check_cache(query, search_type, limit)
        if cached:
            return cached

        query_embedding = self.model.encode([query])[0]

        conn = get_connection()
        cursor = conn.cursor()

        if search_type == 'all':
            cursor.execute('''
                SELECT id, content, content_type, metadata, embedding, topic, source, trust_score, created_at
                FROM knowledge
                ORDER BY trust_score DESC
            ''')
        else:
            cursor.execute('''
                SELECT id, content, content_type, metadata, embedding, topic, source, trust_score, created_at
                FROM knowledge
                WHERE content_type = ?
                ORDER BY trust_score DESC
            ''', (search_type,))

        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return []

        results = []
        for row in rows:
            if row[4]:
                stored_embedding = np.frombuffer(row[4], dtype=np.float32)
                similarity = np.dot(query_embedding, stored_embedding) / (
                    np.linalg.norm(query_embedding) * np.linalg.norm(stored_embedding) + 1e-10
                )
                trust_score = row[7] if row[7] else 0.5
                combined_score = (similarity * 0.7) + (trust_score * 0.3)
            else:
                combined_score = 0
                similarity = 0

            results.append({
                'id': row[0],
                'content': row[1][:800],
                'full_content_length': len(row[1]),
                'type': row[2],
                'metadata': json.loads(row[3]) if row[3] else {},
                'topic': row[5],
                'source': row[6],
                'trust_score': round(row[7], 2) if row[7] else 0.5,
                'relevance_score': round(float(similarity), 4),
                'combined_score': round(float(combined_score), 4),
                'created_at': row[8]
            })

        results.sort(key=lambda x: x['combined_score'], reverse=True)
        results = results[:limit]

        self._cache_results(query, search_type, limit, results)

        logger.info(f"Search '{query}': {len(results)} results")
        return results

    def keyword_search(self, query, limit=20):
        """Fallback keyword-based search"""
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, content, content_type, metadata, source, trust_score, created_at
            FROM knowledge
            WHERE content LIKE ?
            ORDER BY trust_score DESC
            LIMIT ?
        ''', (f'%{query}%', limit))

        rows = cursor.fetchall()
        conn.close()

        return [{
            'id': row[0],
            'content': row[1][:800],
            'type': row[2],
            'metadata': json.loads(row[3]) if row[3] else {},
            'source': row[4],
            'trust_score': row[5],
            'relevance_score': 1.0,
            'combined_score': row[5] if row[5] else 0.5,
            'created_at': row[6]
        } for row in rows]

    def _check_cache(self, query, search_type, limit):
        cache_key = f"{query}:{search_type}:{limit}"
        query_hash = hashlib.md5(cache_key.encode()).hexdigest()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT results, created_at FROM search_cache
            WHERE query_hash = ? AND created_at > datetime('now', '-1 hour')
        ''', (query_hash,))
        row = cursor.fetchone()

        if row:
            cursor.execute('''
                UPDATE search_cache SET hit_count = hit_count + 1 WHERE query_hash = ?
            ''', (query_hash,))
            conn.commit()
            conn.close()
            return json.loads(row[0])

        conn.close()
        return None

    def _cache_results(self, query, search_type, limit, results):
        cache_key = f"{query}:{search_type}:{limit}"
        query_hash = hashlib.md5(cache_key.encode()).hexdigest()

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO search_cache (query_hash, query, results, created_at)
            VALUES (?, ?, ?, ?)
        ''', (query_hash, cache_key, json.dumps(results), datetime.now().isoformat()))
        conn.commit()
        conn.close()
