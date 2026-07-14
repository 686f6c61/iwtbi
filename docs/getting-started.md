# Getting Started

This guide covers the fastest way to run IWTBI locally.

## Prerequisites

- Docker and Docker Compose
- Git
- Credentials for an OpenAI-compatible API or one built-in provider profile

Optional:

- Resend if you want email notifications

## Option 1: Run the full stack with Docker Compose

1. Generate the root environment file and local secrets:

   ```bash
   ./scripts/init-self-host.sh
   ```

2. Fill in the required values:
   - `PROVIDER`
   - provider credentials
   - `OPENAI_COMPATIBLE_API_KEY`
   - `OPENAI_COMPATIBLE_BASE_URL`
   - `OPENAI_COMPATIBLE_MODEL`

3. Start the application:

   ```bash
   docker compose up --build
   ```

4. Open the local services:
   - frontend: `http://localhost:3410`
   - backend health: `http://localhost:8410/health`

## Option 2: Run frontend and backend separately

### Backend

```bash
cp backend/.env.example backend/.env
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cp frontend/.env.example frontend/.env
cd frontend
npm install
npm run dev -- --host 0.0.0.0 --port 4321
```

With the default examples, the frontend expects the API at `http://localhost:8410` when built statically and can point to `http://localhost:8000` if you choose to adjust `frontend/.env` for direct backend development.

## Required services

### PostgreSQL

The default Docker Compose stack starts internal PostgreSQL and applies
`backend/postgres/schema.sql` automatically on first boot. It stores:

- cached analyses
- the public library
- queued email notifications
- future-update subscriptions and email preferences

For backend-only development, start your own PostgreSQL and apply:

```bash
psql "$DATABASE_URL" -f backend/postgres/schema.sql
```

The backend also applies the same schema idempotently on startup when
`DATABASE_URL` is configured.

### LLM provider

Choose one provider through `PROVIDER`:

- `openai_compatible`
- `nan`
- `zai`
- `ollama_cloud`

Only one needs to be configured for the app to run. The generic profile works
with any service that implements the OpenAI chat API; set the base URL, model
identifier and key supplied by that service.

For controlled internal analyses with another model, set `LLM_PROFILES_JSON`
as described in [Configuration](configuration.md). Leave it as `[]` when you do
not need administrative profiles. They are never shown in the public UI.

### Resend

Email notifications are optional. If `RESEND_API_KEY` is empty, analysis still works, but the app will skip notification fanout.

## Smoke test checklist

After the app starts, verify:

1. `GET /health` returns `status: ok` after your provider is configured
2. the homepage loads
3. `POST /api/preflight` accepts a public GitHub repo URL
4. `GET /api/ticket` returns a ticket when called from the allowed frontend origin
5. a new analysis appears in Postgres and then in `/biblioteca`

## Troubleshooting

### The backend refuses to start

Check:

- `DATABASE_URL`
- provider credentials and model name

The backend validates settings on startup and fails fast when required values are missing.

### Preflight says the repository is too large

That is expected behavior when the repository exceeds:

- the candidate file ceiling
- the repository size limit
- the context budget needed for a reliable analysis

Adjust the limits only if you understand the cost and quality tradeoffs.
