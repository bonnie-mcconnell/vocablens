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

## Environment and security

### Production/staging required settings

In non-development environments (`VOCABLENS_ENV=production` or `staging`), the app now enforces a non-default secret at startup.

```env
VOCABLENS_ENV=production
VOCABLENS_SECRET=<strong-random-secret>
```

### CORS settings

Configure CORS explicitly via environment variables (comma-separated lists where applicable):

```env
CORS_ALLOW_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=*
CORS_ALLOW_HEADERS=*
```

### Event ingestion mode

Configure event ingestion behavior explicitly:

```env
EVENT_INGEST_MODE=best_effort
```

Allowed values:

- `best_effort`: buffered/background writes; failed event persistence is logged and dropped.
- `durable`: synchronous persistence; write failures surface to the caller.

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

For Postgres-native migration/concurrency suites, set:

```env
VOCABLENS_TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost/postgres
```

To fail fast in CI when Postgres is unavailable instead of skipping these suites:

```env
VOCABLENS_REQUIRE_POSTGRES_TESTS=true
```

## Running tests

Testing policy and lane definitions are documented in `docs/testing_strategy.md`.

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

### CI-equivalent local runs

Run the same split as `.github/workflows/ci.yml`:

1. Non-Postgres lane (matches `unit-and-lint`):

```bash
.\venv\Scripts\python.exe -m pytest -q ^
  --ignore=tests\test_migrations_postgres.py ^
  --ignore=tests\test_daily_loop_postgres_concurrency.py ^
  --ignore=tests\test_experiment_postgres_concurrency.py ^
  --ignore=tests\test_session_postgres_concurrency.py ^
  --ignore=tests\test_admin_diagnostics_flows_postgres.py ^
  --ignore=tests\test_product_flows_postgres.py
```

2. Strict Postgres lane (matches `postgres-required`):

```bash
$env:VOCABLENS_TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
$env:VOCABLENS_REQUIRE_POSTGRES_TESTS="true"
.\venv\Scripts\python.exe -m pytest -q tests\test_migrations_postgres.py tests\test_daily_loop_postgres_concurrency.py tests\test_experiment_postgres_concurrency.py tests\test_session_postgres_concurrency.py tests\test_admin_diagnostics_flows_postgres.py tests\test_product_flows_postgres.py
```

### CI quickstart

Run lint and the non-Postgres test lane exactly like CI:

```bash
.\venv\Scripts\python.exe -m ruff check .
.\venv\Scripts\python.exe -m pytest -q ^
  --ignore=tests\test_migrations_postgres.py ^
  --ignore=tests\test_daily_loop_postgres_concurrency.py ^
  --ignore=tests\test_experiment_postgres_concurrency.py ^
  --ignore=tests\test_session_postgres_concurrency.py ^
  --ignore=tests\test_admin_diagnostics_flows_postgres.py ^
  --ignore=tests\test_product_flows_postgres.py
```

Then run the strict Postgres lane:

```bash
$env:VOCABLENS_TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
$env:VOCABLENS_REQUIRE_POSTGRES_TESTS="true"
.\venv\Scripts\python.exe -m pytest -q tests\test_migrations_postgres.py tests\test_daily_loop_postgres_concurrency.py tests\test_experiment_postgres_concurrency.py tests\test_session_postgres_concurrency.py tests\test_admin_diagnostics_flows_postgres.py tests\test_product_flows_postgres.py
```

### Strict Postgres lane troubleshooting

If strict Postgres tests fail before running assertions:

1. `password authentication failed`
- The credentials in `VOCABLENS_TEST_DATABASE_URL` do not match your local Postgres instance.
- Update the URL to valid local credentials, or start a clean local Postgres with known credentials.

2. Docker Compose cannot connect to Docker engine
- Ensure Docker Desktop is running before `docker compose up -d postgres`.
- If Docker is unavailable, use a local Postgres installation and set `VOCABLENS_TEST_DATABASE_URL` accordingly.

3. Strict mode expected behavior
- With `VOCABLENS_REQUIRE_POSTGRES_TESTS=true`, setup issues are treated as failures (not skips).

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

## Frontend-ready API

Frontend aggregation endpoints now return a consistent envelope:

```json
{
  "data": { ... },
  "meta": { ... }
}
```

Available endpoints:

- `GET /frontend/dashboard`
- `GET /frontend/recommendations`
- `GET /frontend/weak-areas`

Admin reporting:

- `GET /admin/reports/conversions`
  - requires `X-Admin-Token`

These endpoints are designed to reduce frontend round trips by aggregating
progress, streaks, recommendations, weak areas, and conversion metrics.

## Explain My Thinking

Conversation responses in tutor mode can include a `thinking_explanation` block:

- `grammar_mistake`
- `natural_phrasing`
- `native_level_explanation`
