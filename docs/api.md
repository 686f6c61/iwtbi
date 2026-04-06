# API and SSE Flow

This document describes the public backend surface used by the frontend.

## Base routes

The FastAPI app exposes:

- `GET /health`
- `POST /api/preflight`
- `GET /api/ticket`
- `POST /api/analyze`
- `GET /api/stream/{job_id}`
- `GET /api/biblioteca`
- `GET /api/biblioteca/{owner}/{repo}`

## Endpoint reference

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/health` | `GET` | Healthcheck for local and production deployments |
| `/api/preflight` | `POST` | Measure repository size and context fitness |
| `/api/ticket` | `GET` | Issue a one-shot ticket for analysis |
| `/api/analyze` | `POST` | Start a new analysis or return cached output |
| `/api/stream/{job_id}` | `GET` | Subscribe to SSE progress for a job |
| `/api/biblioteca` | `GET` | Paginated library listing |
| `/api/biblioteca/{owner}/{repo}` | `GET` | Full saved document for a repository |

## Preflight

### Request

```json
{
  "url": "https://github.com/owner/repo"
}
```

### Response

```json
{
  "mode": "normal",
  "reason": "fits_context",
  "candidate_files": 42,
  "selected_files": 18,
  "total_candidate_chars": 25193,
  "selected_chars": 25193,
  "oversized_files": 0,
  "budget_truncated_files": 0,
  "candidate_file_limit": 750
}
```

Possible `mode` values:

- `normal`
- `optimized`
- `too_large`

## Ticket

The frontend must request a ticket before starting analysis.

### Response

```json
{
  "ticket": "uuid-v4-token"
}
```

## Analyze

### Request

```json
{
  "url": "https://github.com/owner/repo",
  "force_new": false,
  "email": "user@example.com"
}
```

The request must include `X-Ticket`.

### Cached response

```json
{
  "cached": true,
  "has_changes": false,
  "document": "# Analysis...",
  "repo_full_name": "owner/repo",
  "updated_at": "2026-04-06T10:00:00+00:00"
}
```

### New job response

```json
{
  "cached": false,
  "job_id": "job-uuid",
  "stream_url": "/api/stream/job-uuid"
}
```

## SSE events

The browser connects to `/api/stream/{job_id}` and receives frames in the standard SSE format.

### Event types

| Event | Meaning |
| --- | --- |
| `status` | Pipeline phase changed |
| `agent` | One agent finished and emitted a section |
| `agent_error` | One agent failed but the run continues |
| `complete` | Final document is ready |
| `analysis_error` | The job failed and cannot complete |

### Example event

```text
event: status
data: {"status":"analyzing"}
```

### Typical status progression

- `cloning`
- `analyzing`
- `synthesizing`

## Library endpoints

### Paginated listing

`GET /api/biblioteca?page=1&page_size=21&sort=updated_desc`

Allowed sort values:

- `updated_desc`
- `updated_asc`
- `name_asc`
- `name_desc`

### Single document lookup

`GET /api/biblioteca/{owner}/{repo}`

Returns the saved row including the full markdown document.

## Security model

The application uses layered controls:

- origin checks at the reverse proxy for write endpoints
- one-shot tickets tied to client fingerprint data
- per-endpoint rate limits
- no direct frontend access to Supabase

Public library reads remain open by design.
