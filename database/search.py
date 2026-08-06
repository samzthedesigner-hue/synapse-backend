import numpy as np
from sentence_transformers import SentenceTransformer
from database.models import get_connection
from config import Config
import logging
import hashlib
import json
import requests
import urllib.parse
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

class SearchEngine:
    def __init__(self):
        self.model = None

    def _load_model(self):
        if self.model is None:
            logger.info("Loading embedding model for search...")
            self.model = SentenceTransformer(Config.EMBEDDING_MODEL)

    def search_and_fetch(self, query, search_type='all', limit=20):
        """
        Search the web, auto-save results, then search local storage.
        This is the main method the frontend calls.
        """
        self._load_model()

        # Step 1: Fetch from external sources and auto-save
        fetched_count = self._fetch_from_web(query)

        # Step 2: Search local storage (which now includes what we just saved)
        results = self._search_local(query, search_type, limit)

        return {
            "query": query,
            "fetched_from_web": fetched_count,
            "results": results,
            "count": len(results)
        }

    def _fetch_from_web(self, query):
        """Fetch knowledge from multiple web sources and auto-save to database"""
        all_items = []
        query_lower = query.lower().strip()

        # Source 1: DuckDuckGo Instant Answer API
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            ddg_resp = requests.get(ddg_url, timeout=10, headers={'User-Agent': 'Synapse/1.0'})
            ddg_data = ddg_resp.json()

            # Abstract (main answer) — this is the direct answer
            abstract = ddg_data.get('AbstractText', '')
            abstract_source = ddg_data.get('AbstractURL', '')
            abstract_title = ddg_data.get('Heading', '')

            if abstract:
                full_content = abstract
                if abstract_title:
                    full_content = abstract_title + "\n\n" + abstract
                if abstract_source:
                    full_content += "\n\nSource: " + abstract_source

                all_items.append({
                    'content': full_content,
                    'type': 'text',
                    'metadata': {
                        'topic': query,
                        'source': abstract_source if abstract_source else 'duckduckgo.com',
                        'fetch_method': 'duckduckgo_abstract',
                        'title': abstract_title
                    }
                })

            # Answer (direct answer box)
            answer = ddg_data.get('Answer', '')
            if answer and answer != abstract:
                all_items.append({
                    'content': "Answer: " + answer,
                    'type': 'text',
                    'metadata': {
                        'topic': query,
                        'source': 'duckduckgo.com',
                        'fetch_method': 'duckduckgo_answer'
                    }
                })

            # Definition
            definition = ddg_data.get('Definition', '')
            if definition:
                all_items.append({
                    'content': "Definition: " + definition,
                    'type': 'text',
                    'metadata': {
                        'topic': query,
                        'source': ddg_data.get('DefinitionSource', 'duckduckgo.com'),
                        'fetch_method': 'duckduckgo_definition'
                    }
                })

            # Related topics — filtered for relevance
            related = ddg_data.get('RelatedTopics', [])
            for topic in related:
                if isinstance(topic, dict) and topic.get('Text'):
                    topic_text = topic.get('Text', '')
                    if self._is_relevant_result(query_lower, topic_text):
                        all_items.append({
                            'content': topic_text,
                            'type': 'text',
                            'metadata': {
                                'topic': query,
                                'source': topic.get('FirstURL', 'duckduckgo.com'),
                                'fetch_method': 'duckduckgo_related'
                            }
                        })

        except Exception as e:
            logger.warning(f"DuckDuckGo fetch failed for '{query}': {e}")

        # Source 2: Wikipedia API
        try:
            wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(query)}"
            wiki_resp = requests.get(wiki_url, timeout=10, headers={'User-Agent': 'Synapse/1.0'})
            if wiki_resp.status_code == 200:
                wiki_data = wiki_resp.json()
                extract = wiki_data.get('extract', '')
                title = wiki_data.get('title', '')

                if extract and not self._is_disambiguation(extract):
                    content = title + "\n\n" + extract
                    all_items.append({
                        'content': content,
                        'type': 'text',
                        'metadata': {
                            'topic': query,
                            'source': wiki_data.get('content_urls', {}).get('desktop', {}).get('page', 'wikipedia.org'),
                            'fetch_method': 'wikipedia_summary',
                            'title': title,
                            'description': wiki_data.get('description', '')
                        }
                    })
        except Exception as e:
            logger.warning(f"Wikipedia fetch failed for '{query}': {e}")

        # Save all fetched items to database
        saved_count = 0
        conn = get_connection()
        cursor = conn.cursor()

        for item in all_items:
            try:
                knowledge_id = str(uuid.uuid4())
                content = item['content']
                content_type = item['type']
                metadata = json.dumps(item['metadata'])
                topic = item['metadata'].get('topic', query)
                source = item['metadata'].get('source', 'unknown')

                content_for_embedding = content[:5000] if len(content) > 5000 else content
                embedding = self.model.encode([content_for_embedding])[0]
                embedding_bytes = embedding.tobytes()

                cursor.execute('''
                    INSERT OR IGNORE INTO knowledge
                    (id, content, content_type, metadata, embedding, topic, source, trust_score, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    knowledge_id, content, content_type, metadata,
                    embedding_bytes, topic, source, 0.6,
                    datetime.now().isoformat()
                ))

                cursor.execute('''
                    INSERT OR IGNORE INTO source_reputation (source, trust_score, total_submissions, first_seen, last_seen)
                    VALUES (?, 0.6, 1, ?, ?)
                ''', (source, datetime.now().isoformat(), datetime.now().isoformat()))

                saved_count += 1
            except Exception as e:
                logger.error(f"Failed to save fetched item: {e}")

        conn.commit()
        conn.close()

        logger.info(f"Fetch-and-save for '{query}': {saved_count} items saved from {len(all_items)} fetched")
        return saved_count

    def _is_relevant_result(self, query, text):
        """Filter out entertainment/media results for factual queries"""
        text_lower = text.lower()

        # If query is clearly factual (what, who, define, how), filter entertainment
        factual_prefixes = ['what is', 'who is', 'define', 'meaning of', 'how does', 'why is', 'when did', 'where is']
        is_factual = any(query.startswith(p) for p in factual_prefixes)

        if is_factual:
            entertainment_markers = [
                'film', 'movie', 'novel', 'album', 'song', 'episode',
                'video game', 'tv series', 'television series', 'book by',
                'directed by', 'starring', 'soundtrack', 'box office',
                'released in', 'season', 'netflix', 'amazon prime'
            ]
            for marker in entertainment_markers:
                if marker in text_lower:
                    query_has_marker = any(m in query for m in entertainment_markers)
                    if not query_has_marker:
                        return False

        return True

    def _is_disambiguation(self, text):
        """Check if Wikipedia returned a disambiguation page"""
        disambig_markers = [
            'may refer to:',
            'may also refer to:',
            'commonly refers to:',
            'is the name of:',
            'can refer to:'
        ]
        first_200 = text[:200].lower()
        for marker in disambig_markers:
            if marker in first_200:
                return True
        return False

    def _search_local(self, query, search_type='all', limit=20):
        """Semantic search across local knowledge base"""
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
                ORDER BY created_at DESC
            ''')
        else:
            cursor.execute('''
                SELECT id, content, content_type, metadata, embedding, topic, source, trust_score, created_at
                FROM knowledge
                WHERE content_type = ?
                ORDER BY created_at DESC
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
        return results

    def search(self, query, search_type='all', limit=20):
        """Simple local search (for browse functionality)"""
        self._load_model()
        return self._search_local(query, search_type, limit)

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
