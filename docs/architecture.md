# Architecture

This document explains how IWTBI is put together and how a repository moves through the system.

## High-level components

### Frontend

- Astro static site
- Served by nginx
- Main pages:
  - `/`
  - `/analyze`
  - `/biblioteca`
  - `/biblioteca/view`
  - `/como-funciona`
  - `/legal`

### Backend

- FastAPI application
- In-memory job store for active runs and one-shot tickets
- Repository cloning and prioritization logic
- Parallel multi-agent analysis pipeline
- SSE stream for real-time progress

### External dependencies

- GitHub for repository clone and metadata
- Internal PostgreSQL for saved analyses, pending email notifications, and future-update preferences
- Resend for optional email delivery
- One LLM provider: NaN, z.ai or Ollama Cloud

## Request lifecycle

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant B as Backend
    participant G as GitHub
    participant L as LLM Provider
    participant P as Postgres
    participant R as Resend

    U->>F: Paste GitHub repo URL
    F->>B: POST /api/preflight
    B->>G: Clone repo temporarily
    B-->>F: mode = normal | optimized | too_large
    F->>B: GET /api/ticket
    B-->>F: X-Ticket token
    F->>B: POST /api/analyze
    B->>P: Check cache
    B->>G: Clone repo
    B->>L: Run 7 agents in parallel
    B->>L: Synthesize final document
    B->>P: Upsert analysis
    B-->>F: SSE progress + final document
    B->>R: Optional email notification
```

## Analysis pipeline

The backend performs the analysis in these phases:

1. Validate the GitHub URL
2. Preflight the repo size and useful context
3. Clone the repository
4. Build a deterministic file tree and prioritized context bundle
5. Run 7 specialized agents in batches of at most 3
6. Ask Margaret Hamilton to integrate and validate the build plan
7. Save the result to PostgreSQL
8. Fan out email notifications if needed

## Agent layout

The current pipeline uses these named analysis agents:

- Grace Hopper (`hopper`): stack and build
- Alan Kay (`kay`): architecture and module map
- Barbara Liskov (`liskov`): database and persistence
- Roy Fielding (`fielding`): APIs and contracts
- Hedy Lamarr (`lamarr`): frontend and UX
- Donald Knuth (`knuth`): business logic and algorithms
- Lynn Conway (`conway`): DevOps and deployment
- Margaret Hamilton (`hamilton`): integration and validation

The seven specialist outputs are preserved verbatim. Margaret Hamilton makes
one independent call after the `3 + 3 + 1` specialist batches to add the
cross-cutting reconstruction plan; if it fails, the backend assembles the same
specialist sections with a deterministic plan.

## File prioritization

The reader does not dump every file into the model context. Instead it:

- walks the full repository tree
- filters out generated or irrelevant directories
- scores files by importance
- includes contents until the global character budget is exhausted

Priority is biased toward:

- `README`
- manifests
- entrypoints
- config files
- schema and migration files
- core source files near the repository root

## Persistence model

Internal PostgreSQL stores the product's durable datasets:

### `analyses`

- cached analysis per repository URL
- final markdown document
- repo full name
- git SHA
- tags/topics from GitHub
- timestamps

### `repo_notifications`

- email subscriptions for in-flight jobs
- one row per requested notification
- `sent_at` timestamp once delivered

### `repo_subscriptions`

- future-update subscriptions per repository and email
- last notified git SHA
- active/unsubscribed state

### `email_preferences`

- global future-update preference per email
- global unsubscribe state

## Failure model

IWTBI is designed to degrade gracefully:

- GitHub metadata failures do not block the analysis
- agent-level failures emit `agent_error` but keep the pipeline running
- synthesis retries before falling back
- email delivery is best-effort and never breaks the main flow

## What is intentionally not public-facing

Internal planning docs, prompt design notes, and implementation planning artifacts live under `docs/superpowers/` in the working repository and are excluded from the public copy generator.
