from flask import Flask, request, jsonify, send_from_directory, Response
from config import Config
from database.store import DataStore
from database.search import SearchEngine
from api.middleware import require_api_key, is_internal_request, check_token_limit
from keys.manager import KeyManager
import threading
import time
import os
import logging

app = Flask(__name__)
app.config.from_object(Config)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

data_store = DataStore()
search_engine = SearchEngine()
key_manager = KeyManager()

# =============================================
# STATIC FILES
# =============================================

@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'dashboard.html')

@app.route('/dashboard/<path:filename>')
def dashboard_static(filename):
    return send_from_directory('static', filename)

# =============================================
# API KEY MANAGEMENT ENDPOINTS
# =============================================

@app.route('/admin/keys/generate', methods=['POST'])
def generate_key():
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    name = data.get('name', 'Unnamed Key')
    token_limit = int(data.get('token_limit', 1000))
    request_limit = int(data.get('request_limit', 10000))
    expires_in_days = int(data.get('expires_in_days', 0))

    key_data = key_manager.create_key(name, token_limit, request_limit, expires_in_days)

    logger.info(f"API key generated: {key_data['id']} ({name})")

    return jsonify({
        "status": "created",
        "key": {
            "id": key_data['id'],
            "api_key": key_data['raw_key'],
            "name": key_data['name'],
            "token_limit": key_data['token_limit'],
            "request_limit": key_data['request_limit'],
            "tokens_used": 0,
            "requests_used": 0,
            "is_active": True,
            "expires_at": key_data['expires_at'],
            "created_at": key_data['created_at']
        },
        "warning": "Save this API key now. It will not be shown again."
    })

@app.route('/admin/keys', methods=['GET'])
def list_keys():
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    keys = key_manager.list_keys()

    return jsonify({
        "keys": keys,
        "total": len(keys)
    })

@app.route('/admin/keys/<key_id>', methods=['GET'])
def get_key(key_id):
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    key_info = key_manager.get_key_info(key_id)

    if not key_info:
        return jsonify({"error": "Key not found"}), 404

    return jsonify(key_info)

@app.route('/admin/keys/<key_id>/revoke', methods=['POST'])
def revoke_key(key_id):
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    success = key_manager.revoke_key(key_id)

    if not success:
        return jsonify({"error": "Key not found"}), 404

    logger.info(f"API key revoked: {key_id}")

    return jsonify({
        "status": "revoked",
        "id": key_id,
        "message": "This key can no longer be used"
    })

@app.route('/admin/keys/<key_id>/limits', methods=['PUT'])
def update_key_limits(key_id):
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    token_limit = data.get('token_limit')
    request_limit = data.get('request_limit')

    success = key_manager.update_limits(key_id, token_limit, request_limit)

    if not success:
        return jsonify({"error": "Key not found"}), 404

    return jsonify({
        "status": "updated",
        "id": key_id,
        "token_limit": token_limit,
        "request_limit": request_limit
    })

@app.route('/admin/stats')
def admin_stats():
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    storage_stats = data_store.get_stats()
    key_stats = key_manager.get_stats()

    return jsonify({
        "storage": storage_stats,
        "keys": key_stats,
        "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0
    })

# =============================================
# INTERNAL ENDPOINTS (called by NeuralForge)
# No API key required
# =============================================

@app.route('/internal/search')
def internal_search():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')
    limit = int(request.args.get('limit', 20))

    if not query:
        return jsonify({"error": "Query parameter 'q' required"}), 400

    results = search_engine.search(query, search_type, limit)
    return jsonify({
        "results": results,
        "count": len(results),
        "query": query
    })

@app.route('/internal/store', methods=['POST'])
def internal_store():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "Content required"}), 400

    content = data['content']
    content_type = data.get('type', 'text')
    metadata = data.get('metadata', {})
    file_data = data.get('file_data')
    file_extension = data.get('file_extension')

    stored_id = data_store.save(content, content_type, metadata, file_data, file_extension)

    if stored_id is None:
        return jsonify({"error": "Storage limit reached for this file type"}), 413

    logger.info(f"Internal store: {stored_id} ({content_type})")

    return jsonify({
        "id": stored_id,
        "status": "stored",
        "type": content_type
    })

@app.route('/internal/knowledge')
def internal_get_knowledge():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    topic = request.args.get('topic', '')
    limit = int(request.args.get('limit', 50))

    if not topic:
        return jsonify({"error": "Topic parameter required"}), 400

    knowledge = data_store.get_by_topic(topic, limit)
    return jsonify({
        "knowledge": knowledge,
        "count": len(knowledge),
        "topic": topic
    })

@app.route('/internal/delete', methods=['DELETE'])
def internal_delete():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    knowledge_id = data.get('id')

    if not knowledge_id:
        return jsonify({"error": "ID required"}), 400

    data_store.delete(knowledge_id)
    return jsonify({"status": "deleted", "id": knowledge_id})

@app.route('/internal/bulk-store', methods=['POST'])
def internal_bulk_store():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    if not data or 'items' not in data:
        return jsonify({"error": "Items array required"}), 400

    items = data['items']
    stored_ids = []

    for item in items:
        content = item.get('content', '')
        content_type = item.get('type', 'text')
        metadata = item.get('metadata', {})
        file_data = item.get('file_data')
        file_extension = item.get('file_extension')
        stored_id = data_store.save(content, content_type, metadata, file_data, file_extension)
        if stored_id:
            stored_ids.append(stored_id)

    logger.info(f"Bulk store: {len(stored_ids)} items")

    return jsonify({
        "stored_ids": stored_ids,
        "count": len(stored_ids),
        "status": "stored"
    })

@app.route('/internal/file/<knowledge_id>')
def internal_get_file(knowledge_id):
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    file_data, file_ext = data_store.get_file(knowledge_id)
    if file_data is None:
        return jsonify({"error": "File not found"}), 404

    mime_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'mp4': 'video/mp4', 'webm': 'video/webm', 'avi': 'video/x-msvideo',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg', 'flac': 'audio/flac',
        'pdf': 'application/pdf', 'json': 'application/json',
        'txt': 'text/plain', 'csv': 'text/csv', 'html': 'text/html',
        'zip': 'application/zip', 'tar': 'application/x-tar', 'gz': 'application/gzip'
    }
    mime = mime_types.get(file_ext.lower(), 'application/octet-stream')
    return Response(file_data, mimetype=mime)

# =============================================
# EXTERNAL ENDPOINTS (API key required)
# Token limits enforced
# =============================================

@app.route('/api/v1/search')
@require_api_key
@check_token_limit
def external_search():
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')
    limit = int(request.args.get('limit', 20))

    if not query:
        return jsonify({"error": "Query parameter 'q' required"}), 400

    results = search_engine.search(query, search_type, limit)

    tokens = len(query.split()) + sum(len(r['content'].split()) for r in results)

    return jsonify({
        "results": results,
        "count": len(results),
        "query": query,
        "tokens_used": tokens
    })

@app.route('/api/v1/store', methods=['POST'])
@require_api_key
@check_token_limit
def external_store():
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "Content required"}), 400

    content = data['content']
    content_type = data.get('type', 'text')
    metadata = data.get('metadata', {})
    file_data = data.get('file_data')
    file_extension = data.get('file_extension')

    stored_id = data_store.save(content, content_type, metadata, file_data, file_extension)

    if stored_id is None:
        return jsonify({"error": "Storage limit reached for this file type"}), 413

    tokens = len(content.split())

    logger.info(f"External store: {stored_id} ({content_type})")

    return jsonify({
        "id": stored_id,
        "status": "stored",
        "type": content_type,
        "tokens_used": tokens
    })

@app.route('/api/v1/knowledge')
@require_api_key
@check_token_limit
def external_get_knowledge():
    topic = request.args.get('topic', '')
    limit = int(request.args.get('limit', 50))

    if not topic:
        return jsonify({"error": "Topic parameter required"}), 400

    knowledge = data_store.get_by_topic(topic, limit)

    tokens = sum(len(k['content'].split()) for k in knowledge)

    return jsonify({
        "knowledge": knowledge,
        "count": len(knowledge),
        "topic": topic,
        "tokens_used": tokens
    })

@app.route('/api/v1/file/<knowledge_id>')
@require_api_key
def external_get_file(knowledge_id):
    file_data, file_ext = data_store.get_file(knowledge_id)
    if file_data is None:
        return jsonify({"error": "File not found"}), 404

    mime_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'mp4': 'video/mp4', 'webm': 'video/webm', 'avi': 'video/x-msvideo',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg', 'flac': 'audio/flac',
        'pdf': 'application/pdf', 'json': 'application/json',
        'txt': 'text/plain', 'csv': 'text/csv', 'html': 'text/html',
        'zip': 'application/zip', 'tar': 'application/x-tar', 'gz': 'application/gzip'
    }
    mime = mime_types.get(file_ext.lower(), 'application/octet-stream')
    return Response(file_data, mimetype=mime)

@app.route('/api/v1/stats')
@require_api_key
def external_stats():
    stats = data_store.get_stats()
    return jsonify(stats)

@app.route('/api/v1/key/info')
@require_api_key
def key_info():
    api_key = request.headers.get('X-API-Key')
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    info = key_manager.get_key_info_by_hash(key_hash)

    if not info:
        return jsonify({"error": "Key not found"}), 404

    return jsonify({
        "name": info['name'],
        "token_limit": info['token_limit'],
        "request_limit": info['request_limit'],
        "tokens_used": info['tokens_used'],
        "requests_used": info['requests_used'],
        "tokens_remaining": info['token_limit'] - info['tokens_used'],
        "requests_remaining": info['request_limit'] - info['requests_used'],
        "is_active": info['is_active'],
        "expires_at": info['expires_at']
    })

# =============================================
# PUBLIC ENDPOINTS
# =============================================

@app.route('/')
def index():
    return jsonify({
        "name": "Synapse Knowledge API",
        "version": "1.0.0",
        "status": "online",
        "endpoints": {
            "dashboard": "/dashboard",
            "internal": "/internal/*",
            "external": "/api/v1/*",
            "health": "/health",
            "admin": "/admin/*"
        }
    })

@app.route('/health')
def health():
    stats = data_store.get_stats()
    return jsonify({
        "status": "healthy",
        "uptime": time.time() - app.start_time if hasattr(app, 'start_time') else 0,
        "storage": stats
    })

# =============================================
# BACKGROUND TASKS
# =============================================

def cleanup_expired_keys():
    """Deactivate expired API keys"""
    while True:
        time.sleep(3600)
        try:
            count = key_manager.deactivate_expired_keys()
            if count > 0:
                logger.info(f"Deactivated {count} expired API keys")
        except Exception as e:
            logger.error(f"Key cleanup error: {e}")

def storage_monitor():
    """Log storage stats periodically"""
    while True:
        time.sleep(43200)  # Every 12 hours
        try:
            stats = data_store.get_stats()
            logger.info(f"Storage stats: {stats['total_items']} items, "
                       f"{stats['file_storage']['total_mb']} MB files, "
                       f"{stats['content_mb']} MB content")
        except Exception as e:
            logger.error(f"Storage monitor error: {e}")

# =============================================
# STARTUP
# =============================================

if __name__ == '__main__':
    app.start_time = time.time()

    # Start background threads
    cleanup_thread = threading.Thread(target=cleanup_expired_keys, daemon=True)
    cleanup_thread.start()

    monitor_thread = threading.Thread(target=storage_monitor, daemon=True)
    monitor_thread.start()

    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
