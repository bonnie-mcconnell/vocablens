# VocabLens

VocabLens is an async FastAPI application for language learning with explicit DI,
Unit of Work transactions, background jobs, personalization, and tutor-mode flows.

## Database migrations

Alembic is the source of truth for schema changes.

### Prerequisites

- Set `DATABASE_URL` to the target database
- For local Postgres, use an async SQLAlchemy URL such as:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/vocablens
```

### Apply migrations

```bash
.\venv\Scripts\python.exe -m alembic upgrade head
```

### Roll back one revision

```bash
.\venv\Scripts\python.exe -m alembic downgrade -1
```

### Roll back to the initial schema

```bash
.\venv\Scripts\python.exe -m alembic downgrade 20260317_0001
```

### Create a new migration

```bash
.\venv\Scripts\python.exe -m alembic revision -m "describe change"
```

If the models changed, review the generated migration carefully before applying it.

## Migration smoke test

This repo includes a migration round-trip test that validates:

- `upgrade -> downgrade -> upgrade` works cleanly
- new product tables exist after upgrade
- required indexes exist
- foreign keys are present

Run it with:

```bash
.\venv\Scripts\python.exe -m pytest tests\test_migrations.py -q
```

## Running tests

Use the project virtual environment:

```bash
.\venv\Scripts\python.exe -m pytest -q
```

Targeted suites:

```bash
.\venv\Scripts\python.exe -m pytest tests\test_api_integration.py -q
.\venv\Scripts\python.exe -m pytest tests\test_jobs_integration.py -q
.\venv\Scripts\python.exe -m pytest tests\test_learning_engine.py -q
```

Current coverage includes:

- auth register/login flow
- token tracking and quota middleware
- learning engine decision logic
- retention engine state classification and action generation
- knowledge graph clustering, weak-cluster analysis, and scheduler behavior
- explain-my-thinking tutor responses and outbound notification delivery
- mistake detection and mistake-pattern storage
- personalization updates and tutor-mode payload behavior
- background job execution paths
- async architecture regression checks
- migration round-trip testing

## Product tables added by migrations

- `usage_logs`
- `subscriptions`
- `mistake_patterns`
- `user_profiles`

These tables include foreign keys back to `users`, non-null constraints for required
fields, and indexes for high-frequency access paths such as `user_id` and timestamps.
`user_profiles` also stores retention fields used by the retention engine:

- `last_active_at`
- `session_frequency`
- `current_streak`
- `longest_streak`
- `drop_off_risk`

## Knowledge graph

The knowledge graph is user-scoped and now supports:

- concept clusters
- word synonym relationships
- grammar links
- weak-cluster detection for recommendation logic

Frequent graph reads are cached, and the learning engine uses weak clusters to
recommend related vocabulary together.

## Notifications

Notifications now support:

- internal logging delivery by default
- optional outbound webhook delivery via:
  - `ENABLE_OUTBOUND_NOTIFICATIONS=true`
  - `NOTIFICATION_WEBHOOK_URL=...`
- persisted delivery attempts/status in `notification_deliveries`

## Subscription tiers

The subscription system now supports feature-based tiers:

- `free`
- `pro`
- `premium`

Feature gates include:

- `tutor_depth`
- `explanation_quality`
- `personalization_level`

Conversion and gate events are tracked in `subscription_events`.

## Explain My Thinking

Conversation responses in tutor mode can include a `thinking_explanation` block:

- `grammar_mistake`
- `natural_phrasing`
- `native_level_explanation`
