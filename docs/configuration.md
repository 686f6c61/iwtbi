# Configuration Reference

IWTBI reads configuration from environment variables.

## Environment files in this repository

- root `.env.example`: local Docker Compose
- `backend/.env.example`: backend-only local development
- `frontend/.env.example`: frontend-only local development
- production deployments should derive their secret environment variables from
  the root `.env.example`

## Provider selection

| Variable | Required | Description |
| --- | --- | --- |
| `PROVIDER` | Yes | `openai_compatible`, `nan`, `zai` or `ollama_cloud` |
| `OPENAI_COMPATIBLE_API_KEY` | If `PROVIDER=openai_compatible` | Key supplied by your provider; local servers may accept any non-empty value |
| `OPENAI_COMPATIBLE_BASE_URL` | If `PROVIDER=openai_compatible` | API base URL, for example `https://api.openai.com/v1` |
| `OPENAI_COMPATIBLE_MODEL` | If `PROVIDER=openai_compatible` | Exact model identifier exposed by your provider |
| `NAN_API_KEY` | If `PROVIDER=nan` | API key for NaN builders |
| `NAN_BASE_URL` | If `PROVIDER=nan` | OpenAI-compatible base URL, defaults to `https://api.nan.builders/v1` |
| `NAN_MODEL` | If `PROVIDER=nan` | Chat model name, defaults to `qwen3.6`; `gemma4` is also available when enabled in NaN |
| `ZAI_API_KEY` | If `PROVIDER=zai` | API key for z.ai |
| `ZAI_BASE_URL` | If `PROVIDER=zai` | OpenAI-compatible base URL, defaults to `https://api.z.ai/api/paas/v4` |
| `ZAI_MODEL` | If `PROVIDER=zai` | Chat model name, defaults to `glm-5.2`; `glm-5-turbo` is a cheaper fallback to benchmark |
| `OLLAMA_CLOUD_API_KEY` | If `PROVIDER=ollama_cloud` | API key for Ollama Cloud |
| `OLLAMA_CLOUD_BASE_URL` | If `PROVIDER=ollama_cloud` | Base URL without `/api` suffix |
| `OLLAMA_CLOUD_MODEL` | If `PROVIDER=ollama_cloud` | Primary Ollama Cloud model, for example `deepseek-v4-pro:cloud` |
| `OLLAMA_CLOUD_FALLBACK_MODELS` | Optional | Comma-separated Ollama Cloud fallback models, for example `kimi-k2.7-code:cloud` |
| `LLM_PROFILES_JSON` | Optional | Private server-side JSON list of profiles for controlled internal analyses |

### Internal per-analysis profiles

`PROVIDER` remains the public default. To run controlled internal analyses with
another server-managed model, define `LLM_PROFILES_JSON` as a single-line JSON
list:

```env
LLM_PROFILES_JSON=[{"id":"zai","label":"z.ai / GLM 5.2","provider":"zai","model":"glm-5.2"},{"id":"local","label":"Modelo local","provider":"openai_compatible","model":"qwen-local","base_url":"http://llm:11434/v1","api_key_required":false}]
```

Each profile accepts `id`, `label`, `provider`, `model`, and optionally
`base_url`, `api_key`, and `api_key_required`. Prefer the provider variables
above instead of putting `api_key` in the JSON. A profile without its own key
inherits the matching `NAN_API_KEY`, `ZAI_API_KEY`,
`OLLAMA_CLOUD_API_KEY`, or `OPENAI_COMPATIBLE_API_KEY`.

Profiles are not listed in the public UI or `/health`, and the public analysis
endpoint rejects `llm_profile_id`. An authorized caller may submit the ID only
to `POST /api/analyze/internal` together with `X-Internal-Token`. API keys and
base URLs stay in the API/worker environment and are never stored in browser
storage, Redis jobs, or the public library. Unknown or unavailable profiles
are rejected before a job is created.

Notes for Ollama Cloud models:
- Models published specifically as Cloud-only should use the exact `:cloud` suffix from Ollama's library, for example `deepseek-v4-pro:cloud`.
- When configured, `OLLAMA_CLOUD_FALLBACK_MODELS` are tried after `OLLAMA_CLOUD_MODEL` and before moving to the next provider fallback.

Notes for NaN:
- The chat model ID is `qwen3.6`; the backend does not invent variants such as `qwen3.6-turbo`.
- The automatic fallback path prefers Ollama Cloud when NaN returns a transient timeout, 429/rate-limit or empty response.

## Runtime and safety limits

| Variable | Default | Description |
| --- | --- | --- |
| `REPO_SIZE_LIMIT_MB` | `100` | Maximum repository size before cloning is blocked |
| `FILE_SIZE_LIMIT_KB` | `500` | Maximum size per text file before truncation/exclusion |
| `MAX_FILES` | `2500` | Maximum files the reader will consider |
| `PREFLIGHT_MAX_CANDIDATE_FILES` | `2500` | Public plan hard stop used by preflight |
| `MAX_CONTEXT_CHARS` | `90000` | Total character budget for prioritized file contents |
| `TRUST_CLOUDFLARE_CLIENT_HEADERS` | `false` | Trust `CF-Connecting-IP` / `True-Client-IP`; enable only when traffic really passes through Cloudflare or the edge proxy strips spoofed values |
| `ANALYZE_RATE_LIMIT` | `10/hour` | Costly analysis endpoint throttle |
| `TICKET_RATE_LIMIT` | `60/minute` | Ticket emission throttle |
| `PREFLIGHT_RATE_LIMIT` | `20/minute` | Repo measurement throttle |

## LLM concurrency and retries

| Variable | Default | Description |
| --- | --- | --- |
| `LLM_AGENT_BATCH_SIZE` | `3` | Independent specialist calls launched per orchestrator batch; maximum 3 |
| `LLM_MAX_CONCURRENCY` | `3` | Process-wide LLM call cap; maximum 3 for every provider |
| `LLM_RETRY_ATTEMPTS` | `3` | Legacy retry setting for generic LLM calls |
| `LLM_RETRY_BASE_DELAY_SECONDS` | `1.5` | Backoff base for generic LLM retries |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Legacy timeout for generic LLM requests |
| `LLM_AGENT_REQUEST_TIMEOUT_SECONDS` | `60` | Per-model timeout for each agent attempt |
| `LLM_AGENT_RETRY_ATTEMPTS` | `0` | Per-model retries for agents; keep low so fallback moves fast |
| `LLM_AGENT_MAX_TOKENS` | `8000` | Max output tokens per agent section |
| `LLM_AGENT_WALL_TIMEOUT_SECONDS` | `180` | Maximum wall time per agent attempt |
| `LLM_SYNTH_REQUEST_TIMEOUT_SECONDS` | `60` | Timeout for synthesis requests |
| `LLM_SYNTH_RETRY_ATTEMPTS` | `0` | Retries for synthesis before moving to fallback/rescue |
| `LLM_SYNTH_RETRY_BASE_DELAY_SECONDS` | `4` | Backoff base for synthesis retries |

## Web and CORS settings

| Variable | Default | Description |
| --- | --- | --- |
| `PUBLIC_BACKEND_URL` | `http://localhost:8410` | Frontend build-time API base URL |
| `PUBLIC_APP_URL` | `http://localhost:3410` | Public frontend URL used in links, SEO and emails |
| `PUBLIC_AUTHOR_URL` / `PUBLIC_AUTHOR_LABEL` | empty | Optional deployment attribution |
| `PUBLIC_SOURCE_URL` | empty | Optional source-code link shown in the footer |
| `PUBLIC_EXTENSION_DOWNLOADS_ENABLED` | `false` | Shows browser-extension downloads only when you publish your own packages |
| `CORS_ORIGINS` | local origins | Allowed frontend origins for the backend |
| `TRUSTED_PROXY_CIDRS` | loopback + private CIDRs | Proxy networks whose forwarded client-IP headers are trusted |
| `INTERNAL_ANALYZE_TOKEN` | empty | Required bearer-style shared secret for `POST /api/analyze/internal`; empty disables the internal route |
| `IWTBI_FRONTEND_PORT` | `3410` | Host port for the frontend container |
| `IWTBI_BACKEND_PORT` | `8410` | Host port for the backend container |

## Persistence and notifications

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_BACKEND` | Yes | Must be `postgres`; other values fail startup |
| `DATABASE_URL` | Yes | PostgreSQL connection URL used for cached analyses and pending email notifications |
| `RESEND_API_KEY` | No | Enables email notifications when provided |
| `RESEND_FROM` | No | Sender email used by Resend |
| `EMAIL_UNSUBSCRIBE_SECRET` | Recommended | HMAC secret for unsubscribe links |
| `EMAIL_UNSUBSCRIBE_TOKEN_TTL_DAYS` | `180` | Expiration window for unsubscribe links |

## Notes

- `PUBLIC_BACKEND_URL` is consumed at frontend build time, not request time.
- The backend targets internal PostgreSQL for cache, library pages, and notification storage.
- Generate URL-safe database secrets with `openssl rand -hex 32`; do not use sample values such as `iwtbi/iwtbi`.
- If `RESEND_API_KEY` is empty, the app still runs; it simply skips emails.
