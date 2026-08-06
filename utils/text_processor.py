import re
from collections import Counter

STOP_WORDS = {
    'the', 'is', 'at', 'which', 'on', 'a', 'an', 'and', 'or', 'but',
    'in', 'with', 'to', 'for', 'of', 'from', 'by', 'as', 'be', 'was',
    'are', 'been', 'this', 'that', 'it', 'its', 'have', 'has', 'had',
    'not', 'no', 'can', 'will', 'would', 'could', 'should', 'may',
    'do', 'does', 'did', 'so', 'if', 'then', 'than', 'too', 'very',
    'just', 'about', 'also', 'into', 'over', 'after', 'before'
}

SPAM_PATTERNS = [
    r'\b(buy now|click here|limited offer|act now|free money)\b',
    r'\b(viagra|casino|lottery|prize|winner)\b',
    r'[A-Z]{10,}',
    r'!{3,}',
    r'\b\d{1,2}/\d{1,2}/\d{2,4}\b',
]

def extract_topics(text):
    if not text:
        return 'general'
    text = text.lower()
    words = re.findall(r'\b[a-z]{3,}\b', text)
    meaningful_words = [w for w in words if w not in STOP_WORDS]
    if not meaningful_words:
        return 'general'
    word_counts = Counter(meaningful_words)
    top_words = word_counts.most_common(3)
    topic = top_words[0][0] if top_words else 'general'
    return topic

def calculate_trust_score(source, content, metadata):
    score = 0.5
    source_score = _get_source_reputation(source)
    score = (score * 0.4) + (source_score * 0.6)
    content_score = _analyze_content_quality(content)
    score = (score * 0.7) + (content_score * 0.3)
    metadata_score = _analyze_metadata(metadata)
    score = (score * 0.9) + (metadata_score * 0.1)
    spam_penalty = _check_spam_indicators(content)
    score *= (1 - spam_penalty)
    return round(max(0.0, min(1.0, score)), 4)

def _get_source_reputation(source):
    try:
        from database.models import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT trust_score FROM source_reputation WHERE source = ?', (source,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return row[0]
        return 0.3
    except Exception:
        return 0.5

def _analyze_content_quality(content):
    if not content:
        return 0.3
    score = 0.5
    length = len(content)
    if length < 50:
        score -= 0.2
    elif 100 <= length <= 5000:
        score += 0.3
    elif length > 10000:
        score += 0.1
    sentences = re.split(r'[.!?]+', content)
    if len(sentences) >= 3:
        score += 0.1
    words = re.findall(r'\b[a-z]{3,}\b', content.lower())
    unique_ratio = len(set(words)) / len(words) if words else 0
    if unique_ratio > 0.5:
        score += 0.1
    return max(0.0, min(1.0, score))

def _analyze_metadata(metadata):
    if not metadata:
        return 0.2
    score = 0.0
    useful_fields = ['source', 'topic', 'author', 'date', 'url', 'category', 'tags']
    for field in useful_fields:
        if field in metadata and metadata[field]:
            score += 0.1
    return min(1.0, score)

def _check_spam_indicators(content):
    if not content:
        return 0.5
    penalty = 0.0
    content_lower = content.lower()
    for pattern in SPAM_PATTERNS:
        matches = re.findall(pattern, content_lower)
        if matches:
            penalty += 0.15 * len(matches)
    urls = re.findall(r'https?://\S+', content)
    url_ratio = len(urls) / max(1, len(content.split()))
    if url_ratio > 0.3:
        penalty += 0.3
    words = content_lower.split()
    if len(words) > 10:
        unique_ratio = len(set(words)) / len(words)
        if unique_ratio < 0.3:
            penalty += 0.4
    return min(1.0, penalty)

def detect_query_language(query):
    if not query:
        return 'unknown'
    lang_indicators = {
        'en': {'the', 'is', 'what', 'how', 'why', 'when', 'where', 'who'},
        'es': {'que', 'como', 'cuando', 'donde', 'quien', 'por', 'para', 'el', 'la'},
        'fr': {'que', 'qui', 'quoi', 'comment', 'pourquoi', 'quand', 'ou'},
    }
    query_lower = query.lower()
    words = set(query_lower.split())
    best_lang = 'en'
    best_score = 0
    for lang, indicators in lang_indicators.items():
        score = len(words & indicators)
        if score > best_score:
            best_score = score
            best_lang = lang
    return best_lang if best_score > 0 else 'en'
