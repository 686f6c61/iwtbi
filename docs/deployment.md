# Deployment Guide

This guide explains how to deploy IWTBI with Docker Compose and a reverse proxy.

## Recommended production topology

- frontend container serving static Astro output through nginx
- backend container serving FastAPI
- reverse proxy terminating TLS
- internal PostgreSQL 18 as persistence
- Redis for queued/background jobs in production
- optional Resend integration for email delivery

## Compose file

The repository includes `docker-compose.prod.yml` for the production stack.

Key behaviors:

- frontend listens on `8080` inside the container
- backend listens on `8000` inside the container
- postgres stores `analyses` and `repo_notifications`
- redis backs distributed job state when `JOB_STORE_BACKEND=redis`
- both services publish only to `127.0.0.1` by default
- the frontend build injects `PUBLIC_BACKEND_URL` at build time

## Production environment

Use `.env.example` as the starting point for a production env file.

At minimum, set:

- one model provider
- `DATABASE_BACKEND=postgres`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `INTERNAL_ANALYZE_TOKEN`
- `CORS_ORIGINS`
- `PUBLIC_BACKEND_URL`
- `PUBLIC_APP_URL`

Optional:

- `RESEND_API_KEY`
- `RESEND_FROM`

## Reverse proxy

For a clean public release, use the generic example in:

- `ops/nginx/site.conf.example`

Adapt these values to your infrastructure:

- frontend hostname
- API hostname
- local upstream ports
- TLS certificate paths

## Deployment steps

1. Prepare the environment file
2. Initialize internal PostgreSQL
3. Build and start the containers
4. Put the reverse proxy in front of them
5. Verify health and end-to-end analysis flow

### Example

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

For the bundled production compose, use the internal service hostname:

```text
POSTGRES_USER=iwtbi_app_<random_suffix>
POSTGRES_PASSWORD=<openssl-rand-hex-32>
DATABASE_URL=postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@postgres:5432/iwtbi
```

Use URL-safe generated values for database credentials. A good default is:

```bash
openssl rand -hex 32
```

## PostgreSQL initialization

The compose files mount this schema into the Postgres init directory:

- `backend/postgres/schema.sql`

The backend and worker also apply the same schema idempotently on startup, so
new tables are created on existing Postgres volumes during normal deploys.

For an already-running database, apply it manually with:

```bash
psql "$DATABASE_URL" -f backend/postgres/schema.sql
```

The repository ships no application data. A fresh volume starts with empty
tables and only the canonical schema.

## Operational checks

After deployment, verify:

1. `/health` returns `status: ok`
2. preflight works from the allowed frontend origin
3. ticket issuance works from the allowed frontend origin
4. an analysis completes and is saved to Postgres
5. the library page can load the saved analysis
6. optional email notifications are delivered

## Notes for self-hosters

- The backend clones public repositories into a temporary directory.
- Redis stores job state and coordinates the API and worker containers.
- Keep PostgreSQL and Redis private; expose only the frontend and API through TLS.
