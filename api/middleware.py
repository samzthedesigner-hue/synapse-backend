from functools import wraps
from flask import request, jsonify
from config import Config
from keys.manager import KeyManager
import hashlib
import hmac
import time
import logging

logger = logging.getLogger(__name__)

_rate_limits = {}
key_manager = KeyManager()

def is_internal_request(request):
    internal_secret = request.headers.get('X-Internal-Secret', '')
    expected = Config.INTERNAL_SECRET

    if internal_secret and hmac.compare_digest(internal_secret, expected):
        return True

    if request.remote_addr in ['127.0.0.1', 'localhost', '::1']:
        return True

    if request.remote_addr and request.remote_addr.startswith('10.'):
        return True

    logger.warning(f"Internal access denied from {request.remote_addr}")
    return False

def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        client_ip = request.remote_addr
        if not _check_rate_limit(client_ip):
            return jsonify({"error": "Rate limit exceeded", "retry_after": 60}), 429

        api_key = request.headers.get('X-API-Key', '')

        if not api_key:
            return jsonify({
                "error": "API key required",
                "message": "Include X-API-Key header"
            }), 401

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        key_info = key_manager.get_key_info_by_hash(key_hash)

        if not key_info:
            return jsonify({"error": "Invalid API key"}), 403

        if not key_info['is_active']:
            return jsonify({
                "error": "API key has been revoked",
                "message": "This key is no longer active"
            }), 403

        if key_info['expires_at']:
            from datetime import datetime
            expiry = datetime.fromisoformat(key_info['expires_at'])
            if datetime.utcnow() > expiry:
                key_manager.revoke_key(key_info['id'])
                return jsonify({"error": "API key has expired"}), 403

        if key_info['requests_used'] >= key_info['request_limit']:
            return jsonify({
                "error": "Request limit reached",
                "limit": key_info['request_limit'],
                "used": key_info['requests_used']
            }), 429

        request.key_info = key_info
        request.api_key_hash = key_hash

        key_manager.increment_requests(key_hash)

        return f(*args, **kwargs)

    return decorated

def check_token_limit(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key_info = getattr(request, 'key_info', None)

        if not key_info:
            return f(*args, **kwargs)

        response = f(*args, **kwargs)

        if response and hasattr(response, 'get_json'):
            try:
                data = response.get_json()
                if data and 'tokens_used' in data:
                    tokens = data['tokens_used']
                    key_manager.increment_tokens(request.api_key_hash, tokens)
            except Exception:
                pass

        return response

    return decorated

def _check_rate_limit(client_ip):
    current_time = time.time()
    window = Config.RATE_LIMIT_WINDOW
    max_requests = Config.RATE_LIMIT_REQUESTS

    if client_ip not in _rate_limits:
        _rate_limits[client_ip] = []

    _rate_limits[client_ip] = [
        t for t in _rate_limits[client_ip]
        if current_time - t < window
    ]

    if len(_rate_limits[client_ip]) >= max_requests:
        return False

    _rate_limits[client_ip].append(current_time)
    return True
