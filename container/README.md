# Circuit Signal - Containerized Platform

Containerized deployment of the Circuit Signal platform using Docker Compose.

## Services

| Service    | Port(s)      | Description                          |
|------------|--------------|--------------------------------------|
| postgres   | 5432         | PostgreSQL 16 with pgvector          |
| redis      | 6379         | Redis 7 (task queue / caching)       |
| minio      | 9000 / 9001  | S3-compatible object storage         |
| api        | 8000         | FastAPI application server           |
| worker     | -            | Background task workers (x2)         |

## Quick Start

```bash
# Copy environment config
cp .env.example .env

# Edit .env to set your ANTHROPIC_API_KEY
vi .env

# Start all services
docker compose up -d

# Run database migrations
docker compose exec api alembic upgrade head

# View logs
docker compose logs -f api worker
```

## Development

```bash
# Rebuild after code changes
docker compose build api worker

# Restart a single service
docker compose restart api

# Stop everything
docker compose down

# Stop and remove volumes (full reset)
docker compose down -v
```

## MinIO Console

The MinIO web console is available at http://localhost:9001. Log in with the credentials from your `.env` file (default: `circuit` / `circuit_dev`).
