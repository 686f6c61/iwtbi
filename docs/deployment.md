# Deployment Guide

This guide explains how to deploy IWTBI with Docker Compose and a reverse proxy.

## Recommended production topology

- frontend container serving static Astro output through nginx
- backend container serving FastAPI
- reverse proxy terminating TLS
- Supabase as managed persistence
- optional Resend integration for email delivery

## Compose file

The repository includes `docker-compose.prod.yml` for the production stack.

Key behaviors:

- frontend listens on `8080` inside the container
- backend listens on `8000` inside the container
- both services publish only to `127.0.0.1` by default
- the frontend build injects `PUBLIC_BACKEND_URL` at build time

## Production environment

Use `ops/env/iwtbi.env.example` as the starting point for a production env file.

At minimum, set:

- one model provider
- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- `CORS_ORIGINS`
- `PUBLIC_BACKEND_URL`

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
2. Initialize Supabase
3. Build and start the containers
4. Put the reverse proxy in front of them
5. Verify health and end-to-end analysis flow

### Example

```bash
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d
```

## Supabase initialization

For a fresh install, apply:

- `backend/supabase/schema.sql`

You can run it through the Supabase SQL editor or with a PostgreSQL client.

## Operational checks

After deployment, verify:

1. `/health` returns `status: ok`
2. preflight works from the allowed frontend origin
3. ticket issuance works from the allowed frontend origin
4. an analysis completes and is saved to Supabase
5. the library page can load the saved analysis
6. optional email notifications are delivered

## Notes for self-hosters

- The backend clones public repositories into a temporary directory.
- The app uses in-memory job state, so active jobs are not resumable across process restarts.
- If you want stronger persistence for active jobs, replace the in-memory store with a durable queue or database-backed job runner.
