# Synapse - Knowledge Data Center

Privacy-first knowledge storage and search engine. Backend for NeuralForge.

## Features

- Semantic search with sentence transformers
- Internal API for NeuralForge (no API key)
- External API with API key management
- Token and request limits per key
- API key revocation (one-click ✕)
- Massive file storage (50-500GB per type)
- Spam-classifier trust scoring
- Admin dashboard for key management

## Storage Limits

| Type | Default Limit |
|------|---------------|
| Text | 50 GB |
| Images | 100 GB |
| Videos | 500 GB |
| Audio | 100 GB |
| Other | 100 GB |

## Deploy to Render

1. Push to GitHub
2. Connect to Render
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
5. Set environment variables

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| INTERNAL_SECRET | Yes | - | Shared secret for NeuralForge |
| ADMIN_SECRET | Yes | - | Admin dashboard access |
| SECRET_KEY | Yes | - | Flask secret key |
| DATABASE_PATH | No | /tmp/synapse_knowledge.db | SQLite path |
| STORAGE_TEXT | No | /tmp/synapse_storage/text | Text files path |
| STORAGE_IMAGES | No | /tmp/synapse_storage/images | Images path |
| STORAGE_VIDEOS | No | /tmp/synapse_storage/videos | Videos path |
| STORAGE_AUDIO | No | /tmp/synapse_storage/audio | Audio path |
| STORAGE_OTHER | No | /tmp/synapse_storage/other | Other files path |
| MAX_STORAGE_TEXT | No | 50 | Max text storage (GB) |
| MAX_STORAGE_IMAGES | No | 100 | Max image storage (GB) |
| MAX_STORAGE_VIDEOS | No | 500 | Max video storage (GB) |
| MAX_STORAGE_AUDIO | No | 100 | Max audio storage (GB) |
| MAX_STORAGE_OTHER | No | 100 | Max other storage (GB) |

## Endpoints

### Admin
- GET/POST /admin/keys — Manage API keys
- POST /admin/keys/{id}/revoke — Revoke key (✕)
- PUT /admin/keys/{id}/limits — Update limits
- GET /admin/stats — System stats
- GET /dashboard — Key management UI

### Internal (NeuralForge)
- GET /internal/search
- POST /internal/store
- POST /internal/bulk-store
- GET /internal/knowledge
- GET /internal/file/{id}
- DELETE /internal/delete

### External (API key)
- GET /api/v1/search
- POST /api/v1/store
- GET /api/v1/knowledge
- GET /api/v1/file/{id}
- GET /api/v1/stats
- GET /api/v1/key/info

### Public
- GET / — API info
- GET /health — Health check
