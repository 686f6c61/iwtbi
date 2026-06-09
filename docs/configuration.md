# Configuration Reference

IWTBI reads configuration from environment variables.

## Environment files in this repository

- root `.env.example`: local Docker Compose
- `backend/.env.example`: backend-only local development
- `frontend/.env.example`: frontend-only local development
- `ops/env/iwtbi.env.example`: production-oriented example

## Provider selection

| Variable | Required | Description |
| --- | --- | --- |
| `PROVIDER` | Only for backend default | `zai` or `ollama_cloud`; the analysis form can override this per request |
| `ZAI_API_KEY` | If `PROVIDER=zai` | API key for z.ai |
| `ZAI_BASE_URL` | If `PROVIDER=zai` | OpenAI-compatible base URL |
| `ZAI_MODEL` | If `PROVIDER=zai` | Model name |
| `OLLAMA_CLOUD_API_KEY` | If `PROVIDER=ollama_cloud` | API key for Ollama Cloud |
| `OLLAMA_CLOUD_BASE_URL` | If `PROVIDER=ollama_cloud` | Base URL without `/api` suffix |
| `OLLAMA_CLOUD_MODEL` | If `PROVIDER=ollama_cloud` | Model name |

The analysis UI also accepts per-analysis credentials for OpenAI, Anthropic,
OpenRouter, Ollama Local, Ollama Cloud, and Z.AI. Those credentials are kept in
the in-memory job only and are not persisted with saved analyses.

## Runtime and safety limits

| Variable | Default | Description |
| --- | --- | --- |
| `REPO_SIZE_LIMIT_MB` | `100` | Maximum repository size before cloning is blocked |
| `FILE_SIZE_LIMIT_KB` | `500` | Maximum size per text file before truncation/exclusion |
| `MAX_FILES` | `2000` | Maximum files the reader will consider |
| `PREFLIGHT_MAX_CANDIDATE_FILES` | `750` | Public plan hard stop used by preflight; set `0` to disable |
| `MAX_CONTEXT_CHARS` | `80000` | Total character budget for prioritized file contents |
| `ANALYZE_RATE_LIMIT` | `5/hour` | Costly analysis endpoint throttle |
| `TICKET_RATE_LIMIT` | `30/minute` | Ticket emission throttle |
| `PREFLIGHT_RATE_LIMIT` | `12/minute` | Repo measurement throttle |

## LLM concurrency and retries

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_MAX_CONCURRENCY` | `4` | Maximum simultaneous LLM requests |
| `LLM_RETRY_ATTEMPTS` | `3` | Retries for standard agent calls |
| `LLM_RETRY_BASE_DELAY_SECONDS` | `1.5` | Backoff base for agent retries |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Timeout for standard agent requests |
| `LLM_SYNTH_REQUEST_TIMEOUT_SECONDS` | `120` | Timeout for synthesis requests |
| `LLM_SYNTH_RETRY_ATTEMPTS` | `2` | Retries for synthesis |
| `LLM_SYNTH_RETRY_BASE_DELAY_SECONDS` | `4` | Backoff base for synthesis retries |

## Web and CORS settings

| Variable | Default | Description |
| --- | --- | --- |
| `PUBLIC_BACKEND_URL` | `http://localhost:8410` | Frontend build-time API base URL |
| `CORS_ORIGINS` | local origins | Allowed frontend origins for the backend |
| `IWTBI_FRONTEND_PORT` | `3410` | Host port for the frontend container |
| `IWTBI_BACKEND_PORT` | `8410` | Host port for the backend container |

## Persistence and notifications

| Variable | Required | Description |
| --- | --- | --- |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Yes | Supabase service role key |
| `RESEND_API_KEY` | No | Enables email notifications when provided |
| `RESEND_FROM` | No | Sender email used by Resend |

## Notes

- `PUBLIC_BACKEND_URL` is consumed at frontend build time, not request time.
- The backend needs Supabase to support cache, library pages, and notification storage.
- If `RESEND_API_KEY` is empty, the app still runs; it simply skips emails.
