# Lunar Dashboard Backend

FastAPI backend for the Lunar Discord bot dashboard.

## Features

- Discord OAuth2 authentication
- Feature flag management with per-guild overrides
- Real-time log streaming via WebSocket
- Usage analytics and command tracking
- Admin control actions (shutdown/restart/reload)
- Rate limiting and CSRF protection
- SQLAlchemy + PostgreSQL (with in-memory fallback)
- Redis pub/sub for bot communication

## Quick Start

```bash
cd dashboard/backend

# Install dependencies
pip install fastapi uvicorn sqlalchemy aioredis httpx python-multipart

# Run with defaults (in-memory store)
uvicorn dashboard.backend.main:app --reload --port 8000

# Run with PostgreSQL + Redis
DATABASE_URL=postgresql://lunar:lunar@localhost:5432/lunar \
REDIS_URL=redis://localhost:6379/0 \
uvicorn dashboard.backend.main:app --reload --port 8000
```

## API Docs

- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | None | PostgreSQL connection string |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |
| `OAUTH_CLIENT_ID` | - | Discord OAuth2 client ID |
| `OAUTH_CLIENT_SECRET` | - | Discord OAuth2 client secret |
| `OAUTH_CALLBACK_URL` | `http://localhost:8000/auth/discord/callback` | OAuth callback URL |
| `DASHBOARD_SECRET` | Random | Cookie signing secret |
| `TOKEN` | - | Discord bot token (for guild proxy) |
| `DASHBOARD_PORT` | 8000 | Server port |

## Endpoints

### Auth
- `GET /auth/discord` - Start Discord OAuth2 flow
- `GET /auth/discord/callback` - OAuth2 callback
- `POST /auth/logout` - Clear session

### Features
- `GET /api/features` - List all features
- `POST /api/features` - Create/update feature (admin)
- `POST /api/features/batch` - Batch update features (admin)

### Guilds
- `GET /api/guilds` - List bot guilds

### Logs
- `GET /api/logs` - Query audit logs
- `WebSocket /ws/logs` - Real-time log stream

### Usage
- `GET /api/usage` - Aggregated usage metrics
- `POST /api/usage` - Record usage event

### Control
- `POST /api/control` - Send control action (admin, rate-limited)

### Admin
- `GET /api/admins` - List admin users (owner)
- `POST /api/admins` - Add admin user (owner)

### Health
- `GET /health` - Health check

## Database Schema

### feature_flags
- id (int, PK)
- name (str, unique)
- description (text)
- data (json)
- updated_at (datetime)
- updated_by (str)

### audit_logs
- id (int, PK)
- actor_id (str)
- action (str)
- target (str)
- details (json)
- created_at (datetime)

### command_usage
- id (int, PK)
- guild_id (str)
- user_id (str)
- command (str)
- timestamp (datetime)
- metadata (json)

### admin_users
- id (int, PK)
- discord_id (str, unique)
- username (str)
- role (str)
- added_at (datetime)
