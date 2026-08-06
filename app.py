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

# Lazy init — don't load models on startup
data_store = None
search_engine = None
key_manager = None

def get_data_store():
    global data_store
    if data_store is None:
        data_store = DataStore()
    return data_store

def get_search_engine():
    global search_engine
    if search_engine is None:
        search_engine = SearchEngine()
    return search_engine

def get_key_manager():
    global key_manager
    if key_manager is None:
        key_manager = KeyManager()
    return key_manager

# =============================================
# STATIC FILES
# =============================================

@app.route('/dashboard')
def dashboard():
    return send_from_directory('static', 'dashboard.html')

# =============================================
# API KEY MANAGEMENT
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

    km = get_key_manager()
    key_data = km.create_key(name, token_limit, request_limit, expires_in_days)

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

    km = get_key_manager()
    keys = km.list_keys()
    return jsonify({"keys": keys, "total": len(keys)})

@app.route('/admin/keys/<key_id>/revoke', methods=['POST'])
def revoke_key(key_id):
    auth_header = request.headers.get('Authorization', '')
    if auth_header != f"Bearer {Config.ADMIN_SECRET}":
        return jsonify({"error": "Unauthorized"}), 401

    km = get_key_manager()
    success = km.revoke_key(key_id)
    if not success:
        return jsonify({"error": "Key not found"}), 404

    return jsonify({"status": "revoked", "id": key_id})

# =============================================
# INTERNAL ENDPOINTS (NeuralForge)
# =============================================

@app.route('/internal/search')
def internal_search():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')
    limit = int(request.args.get('limit', 20))

    if not query:
        return jsonify({"error": "Query required"}), 400

    se = get_search_engine()
    results = se.search(query, search_type, limit)
    return jsonify({"results": results, "count": len(results), "query": query})

@app.route('/internal/store', methods=['POST'])
def internal_store():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "Content required"}), 400

    ds = get_data_store()
    stored_id = ds.save(
        data['content'],
        data.get('type', 'text'),
        data.get('metadata', {}),
        data.get('file_data'),
        data.get('file_extension')
    )

    if stored_id is None:
        return jsonify({"error": "Storage limit reached"}), 413

    return jsonify({"id": stored_id, "status": "stored"})

@app.route('/internal/knowledge')
def internal_get_knowledge():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    topic = request.args.get('topic', '')
    limit = int(request.args.get('limit', 50))

    if not topic:
        return jsonify({"error": "Topic required"}), 400

    ds = get_data_store()
    knowledge = ds.get_by_topic(topic, limit)
    return jsonify({"knowledge": knowledge, "count": len(knowledge), "topic": topic})

@app.route('/internal/delete', methods=['DELETE'])
def internal_delete():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    knowledge_id = data.get('id')
    if not knowledge_id:
        return jsonify({"error": "ID required"}), 400

    ds = get_data_store()
    ds.delete(knowledge_id)
    return jsonify({"status": "deleted", "id": knowledge_id})

@app.route('/internal/bulk-store', methods=['POST'])
def internal_bulk_store():
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    data = request.get_json()
    if not data or 'items' not in data:
        return jsonify({"error": "Items array required"}), 400

    ds = get_data_store()
    items = data['items']
    stored_ids = []

    for item in items:
        sid = ds.save(
            item.get('content', ''),
            item.get('type', 'text'),
            item.get('metadata', {}),
            item.get('file_data'),
            item.get('file_extension')
        )
        if sid:
            stored_ids.append(sid)

    return jsonify({"stored_ids": stored_ids, "count": len(stored_ids)})

@app.route('/internal/file/<knowledge_id>')
def internal_get_file(knowledge_id):
    if not is_internal_request(request):
        return jsonify({"error": "Internal access only"}), 403

    ds = get_data_store()
    file_data, file_ext = ds.get_file(knowledge_id)
    if file_data is None:
        return jsonify({"error": "File not found"}), 404

    mime_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'mp4': 'video/mp4', 'webm': 'video/webm',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
        'pdf': 'application/pdf', 'txt': 'text/plain', 'json': 'application/json'
    }
    mime = mime_types.get(file_ext.lower(), 'application/octet-stream')
    return Response(file_data, mimetype=mime)

# =============================================
# EXTERNAL ENDPOINTS (API key required)
# =============================================

@app.route('/api/v1/search')
@require_api_key
@check_token_limit
def external_search():
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'all')
    limit = int(request.args.get('limit', 20))

    if not query:
        return jsonify({"error": "Query required"}), 400

    se = get_search_engine()
    results = se.search(query, search_type, limit)
    tokens = len(query.split()) + sum(len(r['content'].split()) for r in results)

    return jsonify({"results": results, "count": len(results), "query": query, "tokens_used": tokens})

@app.route('/api/v1/store', methods=['POST'])
@require_api_key
@check_token_limit
def external_store():
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({"error": "Content required"}), 400

    ds = get_data_store()
    stored_id = ds.save(
        data['content'],
        data.get('type', 'text'),
        data.get('metadata', {}),
        data.get('file_data'),
        data.get('file_extension')
    )

    if stored_id is None:
        return jsonify({"error": "Storage limit reached"}), 413

    tokens = len(data['content'].split())
    return jsonify({"id": stored_id, "status": "stored", "type": data.get('type', 'text'), "tokens_used": tokens})

@app.route('/api/v1/knowledge')
@require_api_key
@check_token_limit
def external_get_knowledge():
    topic = request.args.get('topic', '')
    limit = int(request.args.get('limit', 50))

    if not topic:
        return jsonify({"error": "Topic required"}), 400

    ds = get_data_store()
    knowledge = ds.get_by_topic(topic, limit)
    tokens = sum(len(k['content'].split()) for k in knowledge)

    return jsonify({"knowledge": knowledge, "count": len(knowledge), "topic": topic, "tokens_used": tokens})

@app.route('/api/v1/file/<knowledge_id>')
@require_api_key
def external_get_file(knowledge_id):
    ds = get_data_store()
    file_data, file_ext = ds.get_file(knowledge_id)
    if file_data is None:
        return jsonify({"error": "File not found"}), 404

    mime_types = {
        'jpg': 'image/jpeg', 'jpeg': 'image/jpeg', 'png': 'image/png',
        'gif': 'image/gif', 'webp': 'image/webp', 'svg': 'image/svg+xml',
        'mp4': 'video/mp4', 'webm': 'video/webm',
        'mp3': 'audio/mpeg', 'wav': 'audio/wav', 'ogg': 'audio/ogg',
        'pdf': 'application/pdf', 'txt': 'text/plain', 'json': 'application/json'
    }
    mime = mime_types.get(file_ext.lower(), 'application/octet-stream')
    return Response(file_data, mimetype=mime)

@app.route('/api/v1/stats')
@require_api_key
def external_stats():
    ds = get_data_store()
    return jsonify(ds.get_stats())

@app.route('/api/v1/key/info')
@require_api_key
def key_info():
    api_key = request.headers.get('X-API-Key')
    import hashlib
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    km = get_key_manager()
    info = km.get_key_info_by_hash(key_hash)

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
# PUBLIC
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
    return jsonify({"status": "healthy"})

# =============================================
# STARTUP — FOR RENDER
# =============================================

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 10000))
    print(f"Starting Synapse on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # When running with gunicorn
    import os
    print(f"Synapse ready on port {os.environ.get('PORT', '10000')}")
