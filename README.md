# Synapse - Knowledge Data Center

Privacy-first knowledge storage and search engine. Backend for NeuralForge.

## Features

- Semantic search with sentence transformers
- Internal API for NeuralForge (no API key)
- External API with API key management
- Token and request limits per key
- API key revocation (one-click)
- Google Drive auto-backup
- Spam-classifier trust scoring
- Admin dashboard for key management

## Deploy to Render

1. Push to GitHub
2. Connect to Render
3. Build: `pip install -r requirements.txt`
4. Start: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 120`
5. Set environment variables

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| INTERNAL_SECRET | Yes | Shared secret for NeuralForge |
| ADMIN_SECRET | Yes | Admin dashboard access |
| SECRET_KEY | Yes | Flask secret key |
| GOOGLE_DRIVE_ENABLED | No | Enable backup (default: true) |
| GOOGLE_DRIVE_FOLDER_ID | No | Drive folder ID |
| GOOGLE_DRIVE_CREDENTIALS | No | Base64 service account JSON |

## Endpoints

### Admin
- GET/POST /admin/keys — Manage API keys
- POST /admin/keys/{id}/revoke — Revoke key
- GET /admin/stats — System stats
- GET /dashboard — Key management UI

### Internal (NeuralForge)
- GET /internal/search
- POST /internal/store
- POST /internal/bulk-store
- GET /internal/knowledge
- DELETE /internal/delete

### External (API key)
- GET /api/v1/search
- POST /api/v1/store
- GET /api/v1/knowledge
- GET /api/v1/stats
- GET /api/v1/key/info

### Public
- GET / — API info
- GET /health — Health check
