# Getting Started

This guide covers the fastest way to run IWTBI locally.

## Prerequisites

- Docker and Docker Compose
- Git
- A Supabase project
- Credentials for one supported LLM provider:
  - z.ai
  - Ollama Cloud

Optional:

- Resend if you want email notifications

## Option 1: Run the full stack with Docker Compose

1. Copy the root environment file:

   ```bash
   cp .env.example .env
   ```

2. Fill in the required values:
   - `PROVIDER`
   - provider credentials
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`

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

## Required external services

### Supabase

Supabase is required for:

- cached analyses
- the public library
- queued email notifications

For a fresh setup, run `backend/supabase/schema.sql` against your Supabase project, either through the Supabase SQL editor or with your preferred PostgreSQL client.

### LLM provider

Choose one provider through `PROVIDER`:

- `zai`
- `ollama_cloud`

Only one needs to be configured for the app to run.

### Resend

Email notifications are optional. If `RESEND_API_KEY` is empty, analysis still works, but the app will skip notification fanout.

## Smoke test checklist

After the app starts, verify:

1. `GET /health` returns `status: ok`
2. the homepage loads
3. `POST /api/preflight` accepts a public GitHub repo URL
4. `GET /api/ticket` returns a ticket when called from the allowed frontend origin
5. a new analysis appears in Supabase and then in `/biblioteca`

## Troubleshooting

### The backend refuses to start

Check:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_KEY`
- provider credentials

The backend validates settings on startup and fails fast when required values are missing.

### Preflight says the repository is too large

That is expected behavior when the repository exceeds:

- the candidate file ceiling
- the repository size limit
- the context budget needed for a reliable analysis

Adjust the limits only if you understand the cost and quality tradeoffs.
